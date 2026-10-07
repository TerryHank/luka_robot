import unittest
import numpy as np
from seg_depth_geometry import seg_mean_geometry


class TrimmedMeanTests(unittest.TestCase):
    def setUp(self):
        self.intrinsics = dict(fx=100.0, fy=100.0, cx=3.0, cy=3.0)
        self.mask = np.ones((6, 6), dtype=bool)

    def test_discards_low_and_high_depth_outliers_inside_seg_mask(self):
        values = np.array([1.0] * 5 + [2.0] * 26 + [5.0] * 5, dtype=np.float32).reshape(6, 6)
        result = seg_mean_geometry(values, (0, 0, 6, 6), self.mask, self.intrinsics, 0.0)
        self.assertTrue(result['valid'])
        self.assertEqual(result['diagnostic']['method'], 'seg_valid_trimmed_mean')
        self.assertEqual(result['diagnostic']['trimmed_pixels'], 26)
        self.assertAlmostEqual(result['distance_m'], 2.0, places=6)
        self.assertGreater(result['diagnostic']['depth_raw_mean_m'], 2.0)

    def test_filters_out_of_range_depth_before_trimming(self):
        values = np.full((6, 6), 2.0, dtype=np.float32)
        values[0, 0] = 8.0
        result = seg_mean_geometry(values, (0, 0, 6, 6), self.mask, self.intrinsics, 0.0)
        self.assertTrue(result['valid'])
        self.assertEqual(result['diagnostic']['valid_pixels'], 35)
        self.assertAlmostEqual(result['distance_m'], 2.0, places=6)

    def test_filters_invalid_depth_before_trimming(self):
        values = np.full((6, 6), 2.0, dtype=np.float32)
        values[0, 0] = 0.0
        values[0, 1] = np.nan
        result = seg_mean_geometry(values, (0, 0, 6, 6), self.mask, self.intrinsics, 0.0)
        self.assertTrue(result['valid'])
        self.assertEqual(result['diagnostic']['valid_pixels'], 34)
        self.assertAlmostEqual(result['distance_m'], 2.0, places=6)


if __name__ == '__main__':
    unittest.main()
