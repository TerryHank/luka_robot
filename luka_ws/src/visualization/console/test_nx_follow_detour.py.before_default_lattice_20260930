"""Path candidate selection must not route into a blocked side."""
import math
from pathlib import Path
import tempfile
from types import SimpleNamespace as Obj
import unittest

from nx_follow_detour import (active_follow_planner, bounded_hint_goal, costmap_recent,
                              detour_side, map_goal,
                              observation_goal, path_ends_at)


class FollowDetourTest(unittest.TestCase):
    def test_audited_path_requires_fresh_map_costmap(self):
        costmap = Obj(header=Obj(frame_id='map'),
                      metadata=Obj(update_time=Obj(sec=100, nanosec=0)))
        self.assertTrue(costmap_recent(costmap, 100.5))
        self.assertFalse(costmap_recent(costmap, 103.))
        costmap.header.frame_id = 'odom'
        self.assertFalse(costmap_recent(costmap, 100.5))

    def test_audited_path_must_reach_requested_pose_and_heading(self):
        def path(x, y, yaw):
            q = Obj(x=0., y=0., z=math.sin(yaw/2), w=math.cos(yaw/2))
            return Obj(poses=[Obj(pose=Obj(position=Obj(x=x, y=y), orientation=q))])
        self.assertTrue(path_ends_at(path(.4, 0., 0.), (.4, 0., 0.)))
        self.assertFalse(path_ends_at(path(.1, 0., 0.), (.4, 0., 0.)))
        self.assertFalse(path_ends_at(path(.4, 0., .5), (.4, 0., 0.)))

    def test_follow_preplan_must_match_active_navigation_planner(self):
        with tempfile.TemporaryDirectory() as directory:
            bt = Path(directory) / 'nav.xml'
            bt.write_text('<root><PlannerSelector default_planner="GridBased"/></root>')
            self.assertEqual(active_follow_planner(bt), 'GridBased')
            bt.write_text('<root><PlannerSelector default_planner="FootprintAware"/></root>')
            with self.assertRaisesRegex(RuntimeError, '不一致'):
                active_follow_planner(bt)

    def test_one_sided_table_chooses_clear_side(self):
        self.assertEqual(detour_side([(.67, .32), (.8, .25)]), -1)
        self.assertEqual(detour_side([(.67, -.32), (.8, -.25)]), 1)
        self.assertIsNone(detour_side([(.67, .32), (.7, -.3)]))
        self.assertIsNone(detour_side([(.67, 0.)]))

    def test_map_goal_uses_base_heading(self):
        x, y, yaw = map_goal(dict(x=1., y=2., yaw=math.pi/2), .4, -.35)
        self.assertAlmostEqual(x, 1.35)
        self.assertAlmostEqual(y, 2.4)
        self.assertAlmostEqual(yaw, math.pi/2)

    def test_observation_goal_preserves_person_standoff(self):
        target = dict(x=2., y=0.)
        pose = dict(x=0., y=0.)
        x, y, yaw = observation_goal(target, pose)
        self.assertAlmostEqual(x, .40)
        self.assertAlmostEqual(y, 0.)
        self.assertGreaterEqual(math.hypot(target['x']-x, target['y']-y), 1.45)
        self.assertAlmostEqual(yaw, 0.)
        self.assertIsNone(observation_goal(dict(x=1.3,y=0.), pose))

    def test_unmeasured_goal_respects_remaining_travel(self):
        pose = dict(x=1., y=2.)
        hint = dict(waypoint_x=2., waypoint_y=2., waypoint_yaw=0.,
                    remaining_robot_travel_m=.21)
        point = bounded_hint_goal(hint, pose)
        self.assertLessEqual(math.dist(point[:2], (1., 2.)), .17+1e-8)
        hint['remaining_robot_travel_m'] = .08
        self.assertIsNone(bounded_hint_goal(hint, pose))


if __name__ == '__main__':
    unittest.main()
