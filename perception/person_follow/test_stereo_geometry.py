import unittest

import numpy as np

from person_follow.vision import estimate_stereo_person_geometry


class StereoGeometryTest(unittest.TestCase):
    def setUp(self):
        self.depth = np.zeros((480, 640), np.float32)
        self.box = [100, 100, 300, 400]
        self.intrinsic = {'fx': 830., 'cx': 320.}

    def test_sparse_consistent_visible_body_is_approximate(self):
        roi = self.depth[265:370, 150:250]
        roi[:, ::3] = 1.2
        result = estimate_stereo_person_geometry(self.depth, self.box, self.intrinsic)
        self.assertTrue(result['valid'])
        self.assertEqual(result['distance_m'], 1.2)
        self.assertEqual(result['source'], 'stereo_visible_body_approximate')

    def test_too_many_holes_remains_unknown(self):
        self.depth[265:370, 150:250:10] = 1.2
        result = estimate_stereo_person_geometry(self.depth, self.box, self.intrinsic)
        self.assertFalse(result['valid'])
        self.assertEqual(result['reason'], 'insufficient_stereo_body_depth')

    def test_competing_depth_layers_remain_unknown(self):
        roi = self.depth[265:370, 150:250]
        roi[:, :50] = 1.
        roi[:, 50:] = 2.
        result = estimate_stereo_person_geometry(self.depth, self.box, self.intrinsic)
        self.assertFalse(result['valid'])
        self.assertEqual(result['reason'], 'ambiguous_depth_layers')


if __name__ == '__main__':
    unittest.main()
