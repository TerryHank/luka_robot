"""Share the existing RGB-D capture; never open a second USB stream."""
import io
import threading
import time
import cv2
import numpy as np

_packet_lock = threading.Lock()
_packet_cache = {}


def camera_packet(camera, include_zoom=True):
    if hasattr(camera, 'people_snapshot'):
        sample, high = camera.people_snapshot()
    else:
        sample, high = camera.latest, getattr(camera, 'latest_high', None)
    if sample is None:
        raise ValueError('相机尚无画面')
    stamp, monotonic_stamp, rgb, depth, skew = sample
    age = time.monotonic() - monotonic_stamp
    # Passive stereo rectification runs before this packet is available. The
    # source timestamp remains the capture time; allow bounded processing
    # latency without resetting the monitor on an otherwise valid frame.
    if not 0 <= age <= .9:
        raise ValueError('相机画面已过期')
    if rgb.shape[:2] != depth.shape or depth.shape != (480, 640):
        raise ValueError('彩色与深度画面尺寸不匹配')
    key = (id(camera), monotonic_stamp, bool(include_zoom))
    with _packet_lock:
        if _packet_cache and not any(old_key[:2] == key[:2] for old_key in _packet_cache):
            _packet_cache.clear()
        cached = _packet_cache.get(key)
        if cached is not None:
            return cached
        ok, jpeg = cv2.imencode('.jpg', rgb, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ok:
            raise ValueError('相机图像编码失败')
        high_jpeg = np.empty(0, dtype=np.uint8)
        zoom_jpeg = np.empty(0, dtype=np.uint8)
        if high is not None and high[0] == monotonic_stamp:
            high_image = high[1]
            if high_image.shape[:2] in ((960, 1280), (600, 800)):
                ok, high_jpeg = cv2.imencode('.jpg', high_image,
                                            [cv2.IMWRITE_JPEG_QUALITY, 90])
                if not ok:
                    raise ValueError('高清人脸图像编码失败')
        if include_zoom and getattr(camera, 'full_fov_people', False):
            rectified = getattr(camera, 'latest', None)
            if rectified is not None and rectified[1] == monotonic_stamp:
                ok, encoded_zoom = cv2.imencode('.jpg', rectified[2],
                                                [cv2.IMWRITE_JPEG_QUALITY, 82])
                if ok:
                    zoom_jpeg = encoded_zoom
        buffer = io.BytesIO()
        np.savez(buffer, jpeg=jpeg, face_jpeg=high_jpeg, zoom_jpeg=zoom_jpeg,
                 depth=depth.astype(np.uint16, copy=False),
                 stamp=np.float64(stamp), monotonic_stamp=np.float64(monotonic_stamp),
                 skew=np.float64(skew), intrinsic=np.asarray(
                     getattr(camera, 'people_calibration', camera.calibration)['color']),
                 distortion=np.asarray(
                     getattr(camera, 'people_calibration', camera.calibration)['color_dist']),
                 full_fov_people=np.bool_(getattr(camera, 'full_fov_people', False)),
                 metric_depth_available=np.bool_(getattr(camera, 'has_metric_depth', True)))
        packet = buffer.getvalue()
        _packet_cache[key] = packet
        return packet
