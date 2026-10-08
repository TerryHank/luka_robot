"""Bounded live object inventory. This module never issues motion commands.

RGB/OpenNI are approximately paired on the host. Moving frames retain the
capture-time observer pose only; depth positions require a settled robot.
"""
import json
import math
import re
import shutil
import threading
import time
import urllib.request
import uuid
from pathlib import Path

import cv2
import numpy as np

from object_memory import map_position
from semantic_store import SemanticStore


def pose_context(stamp):
    with urllib.request.urlopen('http://127.0.0.1:8503/api/object/pose?stamp='+str(stamp), timeout=1.5) as response:
        return json.load(response)


def startup_context(camera):
    """Wait briefly for the stationary AMCL refresh requested by pose_context.

    No stale pose is accepted: other localization failures fail immediately,
    and the normal per-frame gates remain unchanged after startup.
    """
    deadline = time.monotonic() + 1.5
    while True:
        sample = camera.latest
        if sample is None or not -.1 <= time.time()-sample[0] <= .65:
            raise ValueError('相机画面不可用')
        context = pose_context(sample[0])
        if context.get('localization_valid') and context.get('map_id'):
            return context
        if (not context.get('stationary') or context.get('localization_status') != 'amcl_stale'
                or time.monotonic() >= deadline):
            raise ValueError('当前定位未就绪，不能建立物体地图')
        time.sleep(.2)


def memory_budget():
    """Reserve headroom against an 8 GB target even on the development 16 GB NX."""
    values = {}
    for line in Path('/proc/meminfo').read_text().splitlines():
        parts = line.split()
        values[parts[0].rstrip(':')] = int(parts[1])*1024
    used = values['MemTotal']-values['MemAvailable']
    usable = min(values['MemTotal'], int(7.3*1024**3))
    return {'system_used_gib': round(used/1024**3, 3),
            'available_gib': round(values['MemAvailable']/1024**3, 3),
            'target_headroom_gib': round((usable-used)/1024**3, 3),
            'budget_gib': round(usable/1024**3, 3),
            'swap_used_mib': round((values['SwapTotal']-values['SwapFree'])/1024**2, 1)}


def frame_gate(sample, context, now):
    if sample is None or not -.1 <= now-sample[0] <= .65:
        return 'camera_stale'
    if not context.get('localization_valid') or not context.get('map_id') or not context.get('map_from_base'):
        return 'localization_unavailable'
    if not -.1 <= context.get('odom_age_s', 999) <= .5:
        return 'odometry_stale'
    motion = context.get('motion') or {}
    if abs(motion.get('angular_rps', 999)) > .35:
        return 'turning_too_fast'
    if abs(motion.get('linear_mps', 999)) > .45:
        return 'moving_too_fast'
    return None


def appearance(rgb, box):
    """Conservative crop colour estimate, not a material/brand recognizer."""
    x1, y1, x2, y2 = [int(v) for v in box]
    dx, dy = int((x2-x1)*.2), int((y2-y1)*.2)
    crop = rgb[y1+dy:y2-dy, x1+dx:x2-dx]
    if crop.size < 60:
        return [], None
    crop = cv2.resize(crop, (32, 32))
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    h, s, v = [hsv[:, :, i] for i in range(3)]
    # Brown shares the red/orange hue range, so hue alone turns a dim brown
    # surface into "red". Use only muted, dark warm pixels as brown evidence.
    # Borderline warm pixels abstain instead of falling back to red/orange;
    # saturated reds and bright oranges retain their ordinary colour labels.
    muted_warm = ((h < 23) | (h >= 170)) & (s >= 65) & (s <= 220) & (v <= 190)
    brown = muted_warm & (h >= 3) & (h < 23) & (v >= 50) & (v <= 170)
    masks = {'黑色': v < 45, '白色': (s < 40) & (v > 190),
             '灰色': (s < 40) & (v >= 45) & (v <= 190),
             '棕色': brown,
             '红色': ((h < 10) | (h >= 170)) & (s >= 65) & (v >= 65) & ~muted_warm,
             '橙色': (h >= 10) & (h < 23) & (s >= 65) & (v >= 100) & ~muted_warm,
             '黄色': (h >= 23) & (h < 35) & (s >= 65) & (v >= 100),
             '绿色': (h >= 35) & (h < 85) & (s >= 65) & (v >= 65),
             '蓝色': (h >= 85) & (h < 130) & (s >= 65) & (v >= 65),
             '紫色': (h >= 130) & (h < 170) & (s >= 65) & (v >= 65)}
    fractions = sorted(((float(mask.mean()), key) for key, mask in masks.items()), reverse=True)
    # A mixed crop or dark exposure should not acquire an invented colour.
    colors = [fractions[0][1]] if fractions[0][0] >= .55 and np.mean(v) > 30 else []
    hist = cv2.calcHist([hsv], [0, 1], None, [12, 4], [0, 180, 0, 256]).reshape(-1)
    hist = (hist / max(float(hist.sum()), 1)).tolist()
    return colors, hist


def position_detection(sample, box, label, context, position, calibration, extrinsic):
    if calibration.get('metric_depth_available') is False:
        return None, None, 'stereo_not_calibrated', None
    if not context.get('stationary'):
        return None, None, 'observation_only_moving', None
    if sample[4] > .05:
        return None, None, 'observation_only_pair_skew', None
    if label in ('bottle', 'glass', 'mirror', 'window'):
        return None, None, 'observation_only_transparent_or_reflective', None
    point, quality = position(sample[3], box, calibration['color'], calibration['color_dist'])
    mapped, reason = map_position(point, context, extrinsic)
    return point, mapped, reason, quality


class SemanticMemory:
    def __init__(self, root, camera, model_lock, detector, position, unload_other, unload_detector, detector_loaded):
        self.root = Path(root)/'semantic_memory'
        self.root.mkdir(exist_ok=True)
        self.evidence = self.root/'evidence'
        self.evidence.mkdir(exist_ok=True)
        self.store = SemanticStore(self.root)
        self.camera, self.model_lock = camera, model_lock
        self.detector, self.position, self.unload_other = detector, position, unload_other
        self.unload_detector, self.detector_loaded = unload_detector, detector_loaded
        self.extrinsic_path = Path(root)/'object_memory'/'camera_extrinsic.json'
        self.guard = threading.RLock()
        self.stop_event = threading.Event()
        self.thread = None
        self.evidence_at = {}
        self.latest_image = None
        self.state = {'running': False, 'session_id': None, 'frames': 0, 'skipped': 0,
                      'error': None, 'paused_reason': None, 'last_success_at': None,
                      'interval_s': .5, 'position_policy': 'moving_observer_pose_stationary_depth',
                      'backend': 's100-bpu-yolo11n-coco80'}

    def update(self, **values):
        with self.guard:
            self.state.update(values)

    def status(self):
        with self.guard:
            status = dict(self.state)
        status['stats'] = self.store.stats()
        sample = self.camera.latest
        status['camera_age_s'] = time.time()-sample[0] if sample is not None else None
        return status

    def start(self, body=None):
        body = body or {}
        with self.guard:
            if self.thread and self.thread.is_alive():
                raise ValueError('实时记忆已在运行，请先停止现有观察')
            context = startup_context(self.camera)
            sid = body.get('session_id') or uuid.uuid4().hex
            if not isinstance(sid, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', sid):
                raise ValueError('无效观察任务编号')
            if shutil.disk_usage(self.root).free < 512*1024**2:
                raise ValueError('剩余磁盘空间不足 512 MB')
            self.stop_event.clear()
            self.state.update(running=True, session_id=sid, map_id=context['map_id'],
                              floor_id=context['floor_id'], frames=0, skipped=0, error=None,
                              paused_reason=None, started_at=time.time(), stopped_at=None,
                              last_success_at=None, last_frame_at=None, last_detections=0,
                              memory=None, inference_seconds=None, pairing=None,
                              pair_skew_s=None, sharpness=None)
            self.thread = threading.Thread(target=self.run, daemon=True)
            self.thread.start()
            return {'ok': True, **self.state}

    def stop(self, body=None):
        with self.guard:
            requested = (body or {}).get('session_id')
            if requested and requested != self.state.get('session_id'):
                raise ValueError('观察任务已改变，不停止其他任务')
            self.stop_event.set()
            thread = self.thread
        if thread and thread is not threading.current_thread():
            thread.join(10)
        return {'ok': not bool(thread and thread.is_alive()), **self.status()}

    def asset(self, name):
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}\.jpg', name):
            raise ValueError('无效图片路径')
        return self.evidence/name

    def run(self):
        last_stamp = None
        failures = 0
        try:
            extrinsic = json.loads(self.extrinsic_path.read_text()) if self.extrinsic_path.exists() else None
            while not self.stop_event.is_set():
                started = time.monotonic()
                acquired = False
                try:
                    sample = self.camera.latest
                    if sample is None or sample[0] == last_stamp:
                        self.update(paused_reason='waiting_for_camera')
                        continue
                    context = pose_context(sample[0])
                    if context.get('map_id') != self.state['map_id']:
                        raise RuntimeError('地图已切换，实时记忆已停止；请在新地图重新开始')
                    reason = frame_gate(sample, context, time.time())
                    if reason:
                        self.update(paused_reason=reason, skipped=self.state['skipped']+1)
                        continue
                    if not self.model_lock.acquire(False):
                        self.update(paused_reason='vision_busy', skipped=self.state['skipped']+1)
                        continue
                    acquired = True
                    self.unload_other()
                    budget = memory_budget()
                    self.update(memory=budget)
                    # Live cold-load measurement added ~0.18 GiB. Reserve 0.45
                    # GiB for load/transients on top of 0.65 GiB system headroom.
                    reserve = .65 if self.detector_loaded() else 1.10
                    if budget['target_headroom_gib'] < reserve:
                        self.unload_detector()
                        self.update(paused_reason='memory_budget', skipped=self.state['skipped']+1)
                        continue
                    # Only the latest immutable camera sample is retained, never a video queue.
                    rgb = sample[2].copy()
                    gray = cv2.cvtColor(rgb, cv2.COLOR_BGR2GRAY)
                    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
                    if sharpness < 12:
                        self.update(paused_reason='blurred_frame', skipped=self.state['skipped']+1)
                        continue
                    result = self.detector(rgb)
                    budget = memory_budget()
                    self.update(memory=budget)
                    if budget['target_headroom_gib'] < .65:
                        self.unload_detector()
                        raise RuntimeError('视觉加载后超出8GB目标内存预算，已卸载并停止实时观察')
                    if self.stop_event.is_set():
                        break
                    items = []
                    marked = rgb.copy()
                    for detection in result.get('detections', [])[:50]:
                        if detection.get('label') == 'person' or detection.get('score', 0) < .45:
                            continue
                        box = detection.get('box') or []
                        if len(box) != 4 or not all(math.isfinite(float(v)) for v in box):
                            continue
                        h, w = rgb.shape[:2]
                        box = [max(0, min(w-1, box[0])), max(0, min(h-1, box[1])),
                               max(0, min(w, box[2])), max(0, min(h, box[3]))]
                        if box[2]-box[0] < 8 or box[3]-box[1] < 8:
                            continue
                        colors, hist = appearance(rgb, box)
                        point, mapped, reason, quality = position_detection(sample, box, detection['label'],
                            context, self.position, self.camera.calibration, extrinsic)
                        items.append({'label': detection['label'], 'score': detection['score'],
                                      'box_rgb': box, 'colors': colors, 'appearance': hist,
                                      'map_xyz_m': mapped, 'position_status': reason,
                                      'camera_xyz_m': point, 'depth_quality': quality,
                                      'observation_pose': context['map_from_base']})
                        x1,y1,x2,y2 = [int(v) for v in box]
                        cv2.rectangle(marked, (x1,y1), (x2,y2), (70,220,130), 2)
                        cv2.putText(marked, detection['label']+' %.2f'%detection['score'],
                                    (x1,max(16,y1-4)), cv2.FONT_HERSHEY_SIMPLEX,.5,(70,220,130),1)
                    entities = self.store.ingest(items, context, sample[0], self.state['session_id'])
                    if shutil.disk_usage(self.root).free < 512*1024**2:
                        raise RuntimeError('磁盘空间不足，实时记忆停止')
                    ok, jpeg = cv2.imencode('.jpg', marked, [cv2.IMWRITE_JPEG_QUALITY, 82])
                    evidence_bytes = jpeg.tobytes() if ok else None
                    for entity in entities:
                        ident = entity['id']
                        if not entity['confirmed'] or sample[0]-self.evidence_at.get(ident, 0) < 10:
                            continue
                        path = self.asset(ident+'.jpg')
                        if evidence_bytes:
                            temp = path.with_suffix('.tmp')
                            temp.write_bytes(evidence_bytes); temp.replace(path)
                            self.store.set_evidence(ident, '/semantic/file/'+path.name)
                            self.evidence_at[ident] = sample[0]
                    if evidence_bytes:
                        self.latest_image = evidence_bytes
                    last_stamp = sample[0]
                    failures = 0
                    self.update(frames=self.state['frames']+1, last_success_at=time.time(),
                                last_frame_at=sample[0], last_detections=len(items),
                                inference_seconds=result.get('inference_seconds'),
                                pairing='approximate_host_pairing', pair_skew_s=round(sample[4],4),
                                sharpness=round(sharpness,1), error=None, paused_reason=None)
                except RuntimeError:
                    raise
                except Exception as exc:
                    failures += 1
                    self.update(error=str(exc)[:240], paused_reason='frame_error')
                    if failures >= 5:
                        raise RuntimeError('连续处理失败，实时记忆停止：'+str(exc)) from exc
                finally:
                    if acquired:
                        self.model_lock.release()
                    self.stop_event.wait(max(.05, self.state['interval_s']-(time.monotonic()-started)))
        except Exception as exc:
            self.update(error=str(exc)[:240])
        finally:
            if self.model_lock.acquire(timeout=5):
                try:self.unload_detector()
                finally:self.model_lock.release()
            self.update(running=False, stopped_at=time.time())
