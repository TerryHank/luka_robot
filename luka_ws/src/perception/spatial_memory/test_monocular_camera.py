import time
from unittest.mock import patch

import numpy as np

from camera import object_position
from monocular_camera import MonocularCamera


class FakeCapture:
    def __init__(self):
        self.frame = np.full((960, 1280, 3), 93, np.uint8)
        self.released = False

    def set(self, *args):
        pass

    def read(self):
        time.sleep(.01)
        return True, self.frame

    def release(self):
        self.released = True


def test_monocular_frames_never_claim_calibrated_depth():
    capture = FakeCapture()
    with patch('monocular_camera.cv2.VideoCapture', return_value=capture), patch.dict(
            'os.environ', {'NX_STEREO_CALIBRATION_JSON': '/invalid/old-camera.json'}):
        camera = MonocularCamera('/fake/monocular')
        try:
            deadline = time.monotonic() + 2
            while camera.latest is None and time.monotonic() < deadline:
                time.sleep(.01)
            sample, high = camera.people_snapshot()
            assert sample is not None
            assert sample[2].shape == (480, 640, 3)
            assert high[1].shape == (960, 1280, 3)
            assert not sample[3].any()
            assert not camera.has_metric_depth
            assert not camera.calibration['metric_depth_available']
            position, quality = object_position(sample[3], [100, 100, 300, 400],
                                                camera.calibration['color'], camera.calibration['color_dist'])
            assert position is None
            assert quality['reason'] == 'insufficient_depth'
        finally:
            camera.close()
    assert capture.released
    assert not camera.thread.is_alive()
