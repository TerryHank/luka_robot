import unittest
import numpy as np
from rgbd_geometry import object_position

class GeometryTests(unittest.TestCase):
    def test_optical_axes_and_metres(self):
        depth=np.full((480,640),1500,np.uint16)
        xyz,_=object_position(depth,[360,240,440,320],[500,500,320,240],[0]*5)
        np.testing.assert_allclose(xyz,[.24,.12,1.5],atol=.001)

    def test_invalid_and_mixed_depth(self):
        depth=np.zeros((480,640),np.uint16)
        self.assertIsNone(object_position(depth,[10,10,100,100],[500,500,320,240],[0]*5)[0])
        depth[:]=1000;depth[:,55:]=3000
        self.assertIsNone(object_position(depth,[10,10,100,100],[500,500,320,240],[0]*5)[0])
