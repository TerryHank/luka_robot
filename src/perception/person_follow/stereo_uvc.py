"""Latest-frame UVC stereo source for static person recognition.

The camera exposes left/right images in one side-by-side UVC frame. Depth is
unavailable until this physical camera is stereo-calibrated; this source never
pretends that a disparity image is a metric depth map.
"""
import threading
import time

DEVICE = '/dev/v4l/by-id/usb-SunplusIT_Inc_SPCA2650_PC_Camera_J20260313V0-video-index0'


def split_stereo(frame):
    if frame is None or len(frame.shape) != 3 or frame.shape[2] != 3:
        raise ValueError('双目相机未返回彩色画面')
    height, width = frame.shape[:2]
    if height != 600 or width != 1600:
        raise ValueError(f'双目画面应为 1600×600，实际 {width}×{height}')
    return frame[:, :800].copy(), frame[:, 800:].copy()


class StereoUvc:
    def __init__(self, path=DEVICE):
        import cv2
        self.cv2 = cv2
        self.capture = cv2.VideoCapture(path, cv2.CAP_V4L2)
        if not self.capture.isOpened():
            raise RuntimeError('双目相机未连接或视频设备被占用')
        self.capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
        self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, 1600)
        self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 600)
        self.capture.set(cv2.CAP_PROP_FPS, 30)
        self.capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.lock = threading.Lock()
        self.latest = None
        self.error = None
        self.closed = False
        self.thread = threading.Thread(target=self._read_loop, daemon=True)
        self.thread.start()

    def _read_loop(self):
        failures = 0
        while not self.closed:
            ok, frame = self.capture.read()
            stamp = time.time()
            mono = time.monotonic()
            if not ok:
                failures += 1
                if failures >= 10:
                    with self.lock:
                        self.error = '双目相机连续取帧失败'
                time.sleep(.03)
                continue
            try:
                left, _ = split_stereo(frame)
            except ValueError as exc:
                with self.lock:
                    self.error = str(exc)
                time.sleep(.1)
                continue
            failures = 0
            with self.lock:
                self.latest = (stamp, mono, left)
                self.error = None

    def newest(self, after=None):
        with self.lock:
            if self.error:
                raise RuntimeError(self.error)
            packet = self.latest
        if packet is None:
            raise RuntimeError('双目相机正在启动')
        stamp, mono, left = packet
        if time.monotonic()-mono > .5:
            raise RuntimeError('双目相机画面已过期')
        if after is not None and mono == after:
            return None
        return stamp, mono, left

    def close(self):
        self.closed = True
        self.thread.join(timeout=1)
        self.capture.release()
