"""Passive health observations and bounded navigation incident snapshots."""
import json
import math
import time
import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sensor_msgs.msg import LaserScan, Imu, CompressedImage
from nav_msgs.msg import OccupancyGrid, Odometry
from std_msgs.msg import String
from rcl_interfaces.msg import Log
from lifecycle_msgs.srv import GetState
from rclpy.qos import qos_profile_sensor_data


class RobotDiagnostics:
    def __init__(self, node):
        self.node = node
        self.lock = threading.Lock()
        self.samples = {}
        self.logs = deque(maxlen=80)
        self.latest = None
        self.target = None
        self.writer = ThreadPoolExecutor(max_workers=1)
        self.pending = None
        self.directory = node.workspace / 'log' / 'diagnostics'
        for label, topic, kind in [('IMU转速', '/imu/data', Imu),
                                   ('融合里程计', '/odometry/filtered', Odometry),
                                   ('实时相机', '/camera/color/image_raw/compressed', CompressedImage)]:
            node.create_subscription(kind, topic,
                lambda msg, key=label: self.sensor(key, msg), qos_profile_sensor_data)
        for label, topic in [('高位雷达', '/scan'), ('低位雷达', '/scan_low_filtered')]:
            node.create_subscription(LaserScan, topic,
                lambda msg, key=label: self.scan(key, msg), qos_profile_sensor_data)
        for label, topic in [('定位', '/localization/status'),
                             ('融合', '/dual_laser_fusion/status'),
                             ('导航', '/hotel/navigation_status'),
                             ('视觉识别', '/semantic_mapping/status')]:
            node.create_subscription(String, topic,
                lambda msg, key=label: self.status(key, msg), 10)
        for label, topic in [('全局障碍地图', '/global_costmap/costmap'),
                             ('局部障碍地图', '/local_costmap/costmap')]:
            node.create_subscription(OccupancyGrid, topic,
                lambda msg, key=label: self.costmap(key, msg), qos_profile_sensor_data)
        node.create_subscription(Log, '/rosout', self.log, 100)
        self.nodes = set()
        self.lifecycle = {}
        self.lifecycle_pending = {}
        self.lifecycle_clients = {name: node.create_client(GetState, f'/{name}/get_state')
                                  for name in ('bt_navigator', 'planner_server', 'controller_server')}
        node.create_timer(2.0, self.graph)

    def graph(self):
        names = set(self.node.get_node_names())
        with self.lock:
            self.nodes = names
        now = time.monotonic()
        for name, client in self.lifecycle_clients.items():
            pending = self.lifecycle_pending.get(name)
            if pending:
                future, started = pending
                if future.done():
                    try:
                        state = future.result().current_state
                        with self.lock:
                            self.lifecycle[name] = (now, state.id == 3, state.label)
                    except Exception:
                        pass
                    del self.lifecycle_pending[name]
                elif now-started > 4:
                    future.cancel()
                    del self.lifecycle_pending[name]
                continue
            if client.service_is_ready():
                self.lifecycle_pending[name] = (client.call_async(GetState.Request()), now)

    def sensor(self, key, msg):
        now = time.monotonic()
        stamp = msg.header.stamp.sec + msg.header.stamp.nanosec / 1e9
        source_age = self.node.get_clock().now().nanoseconds / 1e9 - stamp
        if key == 'IMU转速':
            valid = msg.angular_velocity_covariance[0] != -1 and all(math.isfinite(x) for x in
                (msg.angular_velocity.x, msg.angular_velocity.y, msg.angular_velocity.z))
        elif key == '实时相机':
            valid = len(msg.data) > 0
        else:
            q = msg.pose.pose.orientation
            valid = all(math.isfinite(x) for x in (q.x, q.y, q.z, q.w)) and sum(
                x*x for x in (q.x, q.y, q.z, q.w)) > 0.5
        with self.lock:
            self.samples[key] = dict(received=now, stamp=stamp, source_age=source_age,
                                    frame=msg.header.frame_id, valid=bool(valid))

    def scan(self, key, msg):
        now = time.monotonic()
        with self.lock:
            if now - self.samples.get(key, {}).get('received', 0) < 0.5:
                return
        values = [float(x) if math.isfinite(x) else None for x in msg.ranges]
        valid = [x for x in values if x is not None and msg.range_min <= x <= msg.range_max]
        with self.lock:
            self.samples[key] = dict(received=now, frame=msg.header.frame_id,
                stamp=msg.header.stamp.sec + msg.header.stamp.nanosec / 1e9,
                valid=len(valid), nearest=min(valid) if valid else None,
                ranges=values, angle_min=msg.angle_min, angle_increment=msg.angle_increment)

    def costmap(self, key, msg):
        now = time.monotonic()
        with self.lock:
            if now - self.samples.get(key, {}).get('received', 0) < 2.0:
                return
        if len(msg.data) > 300000:
            return
        value = dict(received=now, frame=msg.header.frame_id, width=msg.info.width,
            height=msg.info.height, resolution=msg.info.resolution,
            origin=[msg.info.origin.position.x, msg.info.origin.position.y], data=list(msg.data))
        with self.lock:
            self.samples[key] = value

    def log(self, msg):
        if msg.level >= 30 and any(s in msg.name for s in ('planner', 'controller', 'navigator', 'behavior', 'localiz', 'imu', 'person_follow', 'semantic_mapping')):
            with self.lock:
                self.logs.append(dict(time=msg.stamp.sec, node=msg.name, message=msg.msg[:1200]))

    def status(self, key, msg):
        now = time.monotonic()
        with self.lock:
            self.samples[key] = dict(received=now, text=msg.data[:3000])
        if key != '导航':
            return
        try:
            payload = json.loads(msg.data)
        except ValueError:
            return
        if not isinstance(payload, dict):
            return
        if payload.get('state') == 'accepted':
            self.target = dict(payload, received_at=time.time())
        if payload.get('state') != 'failed':
            return
        with self.lock:
            evidence = dict(recorded_at=time.time(), failure=payload, target=self.target,
                samples=dict(self.samples), warnings=list(self.logs))
        with self.node.lock:
            evidence.update(pose=self.node.pose, map=dict(self.node.map_info), path=list(self.node.path))
        evidence['floor_id'] = self.node.current_floor_id
        start = (self.target or {}).get('received_at', evidence['recorded_at']-30)
        evidence['warnings'] = [x for x in evidence['warnings'] if x['time'] >= start-1]
        messages = ' '.join(x['message'] for x in evidence['warnings'])
        evidence['summary'] = next((description for token, description in (
            ('Starting point in lethal space', '规划起点被标为障碍；需核对车身回波、真实障碍及定位'),
            ('Failed to transform', '导航坐标变换失败'),
            ('no valid path', '规划器未找到有效路径'),
            ('Failed to make progress', '小车未取得足够移动进展'),
            ('Collision Ahead', '恢复动作被碰撞检查阻止'),
        ) if token in messages), '导航失败；请查看原始错误及现场数据')
        evidence['note'] = 'Passive snapshot; each sample has its own age, not a synchronized recording.'
        evidence['samples'] = {k: dict(v, age_sec=round(now-v['received'], 3))
                               for k, v in evidence['samples'].items()}
        if self.pending and not self.pending.done():
            self.latest = {'status': '保存忙，本次未保存'}
            return
        self.pending = self.writer.submit(self.save, evidence)

    def save(self, evidence):
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            if len(list(self.directory.glob('incident-*.json'))) >= 100:
                self.latest = {'status': '记录已满100份，请归档后继续保存'}
                return
            path = self.directory / f'incident-{time.time_ns()}.json'
            path.write_text(json.dumps(evidence, ensure_ascii=False, allow_nan=False), encoding='utf-8')
            self.latest = {'status': '已保存', 'file': str(path), 'failure': evidence['failure'], 'summary': evidence['summary']}
        except Exception as exc:
            self.latest = {'status': f'保存失败：{exc}'}

    def snapshot(self):
        now = time.monotonic()
        with self.lock:
            values = dict(self.samples)
            nodes = set(self.nodes)
            lifecycle = dict(self.lifecycle)
        rows = []
        for key in ('高位雷达', '低位雷达', '融合'):
            value = values.get(key)
            age = now-value['received'] if value else None
            ok = age is not None and age < 3
            if key == '融合':
                ok = ok and 'healthy=true' in value.get('text', '')
            else:
                ok = ok and value.get('valid', 0) > 0
            rows.append(dict(label=key, ok=bool(ok), detail=f'{age:.1f}秒前收到' if age is not None else '尚未收到数据'))
        loc = values.get('定位', {})
        for key, threshold in [('IMU转速', 0.6), ('融合里程计', 0.6), ('实时相机', 1.0)]:
            value = values.get(key)
            if value is None:
                rows.append(dict(label=key, ok=False, detail='尚未收到数据；节点在线不代表传感器正常'))
                continue
            arrival_age = now-value['received']
            source_age = value['source_age']+arrival_age
            ok = value['valid'] and arrival_age <= threshold and -0.2 <= source_age <= threshold
            detail = f'数据年龄 {max(0.0, source_age):.2f}秒'
            if not value['valid']:
                detail = '数据无效'
            elif source_age < -0.2:
                detail = '时间戳超前，请检查时钟'
            elif not ok:
                detail += '，数据过期/中断'
            rows.append(dict(label=key, ok=bool(ok), detail=detail))
        vision = values.get('视觉识别')
        age = now-vision['received'] if vision else None
        # Current NPU semantic inference is deliberately limited to 0.2 Hz.
        fresh = age is not None and age < 15.0
        rows.append(dict(label='视觉识别', ok=bool(fresh and vision.get('text', '').startswith('running')),
            detail=(vision['text']+f'（{age:.1f}秒前）') if fresh else '识别状态过期或节点离线'))
        rows.append(dict(label='定位', ok=None, detail=loc.get('text', '尚未收到定位状态') + '（最近上报，非实时质量判定）'))
        for label, required in [('导航节点', {'bt_navigator','controller_server','planner_server','ddsm_mission_control'}),
                                ('语音节点', {'voice_gateway','nav_llm_agent'})]:
            missing = required-nodes
            rows.append(dict(label=label, ok=not missing, detail='节点在线，未验证服务激活状态' if not missing else '缺少：'+','.join(sorted(missing))))
        for name in self.lifecycle_clients:
            value = lifecycle.get(name)
            fresh = value is not None and now-value[0] < 6
            rows.append(dict(label=name, ok=bool(fresh and value[1]),
                             detail=value[2] if fresh else '激活状态未知或检查超时'))
        return dict(checks=rows, latest_incident=self.latest)
