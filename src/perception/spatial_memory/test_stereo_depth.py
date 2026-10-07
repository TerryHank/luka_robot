import unittest

import numpy as np

from stereo_depth import disparity_to_mm


class StereoDepthTest(unittest.TestCase):
    def test_half_resolution_disparity_converts_to_metres(self):
        result = disparity_to_mm(np.array([[50., 25.]], np.float32), 100.)
        self.assertEqual(result.tolist(), [[1000, 2000]])

    def test_invalid_and_out_of_range_stay_unknown(self):
        result = disparity_to_mm(np.array([[0., -2., np.nan, 1., 127.]], np.float32), 100.)
        self.assertEqual(result.tolist(), [[0, 0, 0, 0, 394]])


if __name__ == '__main__':
    unittest.main()
