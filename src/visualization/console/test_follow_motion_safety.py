import unittest
from web_teleop_safety import follow_motion_blocked


class FollowMotionSafetyTests(unittest.TestCase):
    def test_front_and_turn_sweep(self):
        self.assertTrue(follow_motion_blocked([(.34, .0), (.35, .02)], .2, 0.))
        self.assertTrue(follow_motion_blocked([(.1, .35), (.12, .36)], 0., .2))
        self.assertTrue(follow_motion_blocked([(.1, -.35), (.12, -.36)], .1, -.2))
        self.assertTrue(follow_motion_blocked([(-.35, .0), (-.36, .02)], -.1, 0.))
        self.assertFalse(follow_motion_blocked([(1., 1.)], .2, .2))


if __name__ == '__main__':
    unittest.main()
