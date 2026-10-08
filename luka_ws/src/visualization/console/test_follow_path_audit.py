"""The follow path gate must reject a swept-body collision, not just a bad centerline."""
import math
from types import SimpleNamespace as Obj
import unittest

from follow_path_audit import path_audit


def stamped(x, y, yaw=0.):
    q = Obj(x=0., y=0., z=math.sin(yaw/2), w=math.cos(yaw/2))
    return Obj(pose=Obj(position=Obj(x=x, y=y), orientation=q))


def grid():
    info = Obj(resolution=.05, size_x=100, size_y=100,
               origin=Obj(position=Obj(x=-2.5, y=-2.5)))
    return Obj(metadata=info, data=[0]*10_000)


class FollowPathAuditTest(unittest.TestCase):
    def test_clear_short_path_passes(self):
        path = Obj(header=Obj(frame_id='map'), poses=[stamped(0, 0), stamped(.4, 0)])
        result = path_audit(path, grid(), 1.5)
        self.assertTrue(result['safe'], result)
        self.assertAlmostEqual(result['length_m'], .4)

    def test_footprint_corner_contact_is_rejected(self):
        costmap = grid()
        # Obstacle lies off the centerline, inside the right side of the body.
        gx = math.floor((.2+2.5)/.05)
        gy = math.floor((-.18+2.5)/.05)
        costmap.data[gy*100+gx] = 254
        path = Obj(header=Obj(frame_id='map'), poses=[stamped(0, 0), stamped(.4, 0)])
        result = path_audit(path, costmap, 1.5)
        self.assertFalse(result['safe'])
        self.assertEqual(result['reason'], '车身扫掠触及障碍')

    def test_inflation_buffer_is_reported_without_calling_it_collision(self):
        costmap = grid()
        gx = math.floor((.2+2.5)/.05)
        gy = math.floor((-.18+2.5)/.05)
        costmap.data[gy*100+gx] = 253
        path = Obj(header=Obj(frame_id='map'), poses=[stamped(0, 0), stamped(.4, 0)])
        result = path_audit(path, costmap, 1.5)
        self.assertTrue(result['safe'])
        self.assertGreater(result['inscribed'], 0)
        self.assertIn('膨胀缓冲区', result['reason'])

    def test_unknown_and_large_rotation_fail_closed(self):
        costmap = grid()
        costmap.data[50*100+50] = 255
        path = Obj(header=Obj(frame_id='map'), poses=[stamped(0, 0), stamped(.4, 0)])
        self.assertFalse(path_audit(path, costmap, 1.5)['safe'])
        clear = grid()
        rotating = Obj(header=Obj(frame_id='map'), poses=[stamped(0, 0), stamped(.1, 0, math.pi)])
        self.assertEqual(path_audit(rotating, clear, 1.5)['reason'], '路径过长或转向过大')


if __name__ == '__main__':
    unittest.main()
