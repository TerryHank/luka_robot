"""UVC color frames with explicitly unavailable metric depth."""
import os
import threading
import time

import cv2
import numpy as np


class MonocularCamera:
    def __init__(self, device=None):
        self.device = device or os.environ['NX_CAMERA_DEVICE']
        self.latest = None
        self.latest_high = None
        self.latest_lock = threading.Lock()
        self.error = None
        self.stopping = False
        self.has_metric_depth = False
        self.full_fov_people = False
        self.calibration = {
            'source': 'uvc_mono_uncalibrated', 'metric_depth_available': False,
            'color': [0., 0., 0., 0.], 'color_dist': [0.] * 5,
            'depth': [0.] * 4, 'depth_dist': [0.] * 5,
            'rotation': [0.] * 9, 'translation': [0.] * 3,
        }
        self.people_calibration = dict(self.calibration)
        self.color = self._open()
        self.thread = threading.Thread(target=self._capture, daemon=True)
        self.thread.start()

    def _open(self):
        capture = cv2.VideoCapture(self.device, cv2.CAP_V4L2)
        capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 960)
        capture.set(cv2.CAP_PROP_FPS, 30)
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return capture

    def _capture(self):
        invalid_depth = np.zeros((480, 640), dtype=np.uint16)
        while not self.stopping:
            ok, frame = self.color.read()
            if not ok or frame is None:
                self.error = 'UVC monocular camera frame unavailable'
                self.color.release()
                time.sleep(1)
                if not self.stopping:
                    self.color = self._open()
                continue
            stamp, mono = time.time(), time.monotonic()
            rgb = cv2.resize(frame, (640, 480))
            with self.latest_lock:
                self.latest_high = (mono, frame)
                self.latest = (stamp, mono, rgb, invalid_depth, 0.)
            self.error = None

    def people_snapshot(self):
        with self.latest_lock:
            return self.latest, self.latest_high

    def close(self):
        self.stopping = True
        self.thread.join(timeout=2)
        self.color.release()
