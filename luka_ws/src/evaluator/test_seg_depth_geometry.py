import sys,unittest
import numpy as np
sys.path.insert(0,'/home/sunrise/luka_ws/perception/person_follow')
from seg_depth_geometry import seg_mean_geometry
class SegDepthTests(unittest.TestCase):
 def setUp(self):
  self.depth=np.full((40,40),9.,dtype=np.float32)
  self.mask=np.zeros((20,20),bool);self.mask[5:15,5:15]=True
  self.depth[15:25,15:25]=2.
  self.K={'fx':100.,'fy':100.,'cx':20.,'cy':20.}
 def call(self,**kw):
  args=dict(depth=self.depth,bbox=[10,10,30,30],person_mask=self.mask,intrinsics=self.K,skew_s=.01);args.update(kw)
  return seg_mean_geometry(**args)
 def test_background_excluded_and_arithmetic_mean(self):
  self.depth[15,15:25]=4.
  r=self.call();self.assertTrue(r['valid']);self.assertAlmostEqual(r['distance_m'],2.2)
  self.assertEqual(r['diagnostic']['valid_pixels'],100)
 def test_zero_nan_inf_excluded(self):
  self.depth[15,15:18]=[0,np.nan,np.inf]
  r=self.call();self.assertTrue(r['valid']);self.assertAlmostEqual(r['distance_m'],2.)
  self.assertEqual(r['diagnostic']['valid_pixels'],97)
 def test_no_mask_no_box_fallback(self):self.assertFalse(self.call(person_mask=None)['valid'])
 def test_shape_mismatch(self):self.assertFalse(self.call(person_mask=np.ones((19,20)))['valid'])
 def test_insufficient_depth(self):
  self.depth[15:25,15:25]=0
  self.assertFalse(self.call()['valid'])
 def test_timestamp_skew(self):self.assertFalse(self.call(skew_s=.06)['valid'])
 def test_projection_and_distortion(self):
  self.K['distortion']=[0]*8
  r=self.call();self.assertTrue(r['valid']);np.testing.assert_allclose(r['diagnostic']['position_optical_m'],[-.01,-.01,2])
if __name__=='__main__':unittest.main()