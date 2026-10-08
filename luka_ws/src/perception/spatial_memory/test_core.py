"""Tests for incorrect spatial association and misleading remembered positions."""
import pathlib
import tempfile
import time
import unittest
import numpy as np
from camera import object_position
from memory import Memory


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self.temp.name)/'memory.sqlite3'
        self.memory = Memory(self.path)
        self.ts = time.time()-20

    def tearDown(self):
        self.temp.cleanup()

    def detection(self,box=None,xyz=None):
        return {'class':'cup','bbox':box or [20,30,80,110],
                                      'confidence':.8,'xyz_m':xyz or [.1,.2,1.2]}

    def test_confirmation_persistence_and_not_current(self):
        for i in range(2):
            self.memory.update([self.detection()],'fixed',self.ts+i)
            self.assertEqual(self.memory.search('杯子在哪里','fixed')['count'],0)
        self.memory.update([self.detection()],'fixed',self.ts+2)
        self.memory.update([],'fixed',self.ts+3)
        restarted = Memory(self.path)
        result = restarted.search('杯子在哪里','fixed')
        self.assertEqual(result['count'],1)
        self.assertFalse(result['objects'][0]['recently_seen'])
        self.assertEqual(restarted.search('杯子在哪里','moved-camera')['count'],0)

    def test_two_cups_and_depth_discontinuity(self):
        for i in range(3):
            self.memory.update([self.detection(),self.detection([350,20,420,100],[.8,.2,1.2])],'fixed',self.ts+i)
        self.assertEqual(self.memory.search('cup','fixed')['count'],2)
        for i in range(3):
            self.memory.update([self.detection(xyz=[.1,.2,2.2])],'fixed',self.ts+4+i)
        self.assertEqual(self.memory.search('cup','fixed')['count'],3)

    def test_depth_failure_does_not_reuse_old_distance(self):
        for i in range(3):
            self.memory.update([self.detection()],'fixed',self.ts+i)
        item=self.detection();item['xyz_m']=None
        self.memory.update([item],'fixed',self.ts+3)
        self.assertIsNone(self.memory.search('cup','fixed')['objects'][0]['xyz_m'])


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


if __name__=='__main__':
    unittest.main()
