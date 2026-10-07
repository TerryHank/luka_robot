"""Map follow may bridge a brief range gap, never a lost identity or pose."""
import math
import unittest

from nx_follow_map import MapFollowEstimate


def context(frame, x=0., y=0., yaw=0., valid=True):
    return dict(captured_at=frame, localization_valid=valid,
                map_scope_valid=True, map_pose_status='tf_at_capture_time',
                floor_id='floor_4', map_id='floor_4:test', map_version='test',
                map_from_base=dict(translation=[x, y, 0.],
                                   quaternion_xyzw=[0., 0., math.sin(yaw/2),
                                                    math.cos(yaw/2)]))


def reading(frame, distance=2.2, bearing=0., track_id=3):
    return dict(frame_at=frame, metric_depth_available=True,
                target_session=dict(active=True, visible=True,
                                    profile_id='owner', track_id=track_id),
                tracks=[dict(track_id=track_id, visible=True,
                             observation_strength='strong',
                             association_ambiguous=False,
                             depth_valid=distance is not None,
                             distance_m=distance,
                             bearing_rad=bearing if distance is not None else None,
                             bbox_bearing_rad=bearing)])


class MapFollowTest(unittest.TestCase):
    def test_short_visible_range_gap_produces_bounded_observation_waypoint(self):
        estimate = MapFollowEstimate()
        estimate.observe(reading(100.), context(100.), now=10.)
        self.assertAlmostEqual(estimate.anchor['x'], 2.38)
        missing = reading(100.4, distance=None)
        estimate.observe(missing, context(100.4, x=.05), now=10.4)
        hint = estimate.hint(missing, now=10.5)
        self.assertIsNotNone(hint)
        self.assertAlmostEqual(hint['distance_m'], 2.15, places=2)
        self.assertGreater(hint['waypoint_x'], 0.)
        self.assertGreater(hint['waypoint_forward_m'], .5)
        self.assertAlmostEqual(hint['waypoint_heading_error_rad'], 0.)
        self.assertLess(hint['remaining_robot_travel_m'], .25)
        self.assertIsNone(estimate.hint(missing, now=11.3))

    def test_never_bridge_new_track_bad_map_bearing_or_excess_travel(self):
        estimate = MapFollowEstimate()
        estimate.observe(reading(100.), context(100.), now=10.)
        switched = reading(100.4, distance=None, track_id=4)
        estimate.observe(switched, context(100.4), now=10.4)
        self.assertIsNone(estimate.hint(switched, now=10.5))
        self.assertIsNone(estimate.anchor)

        estimate.observe(reading(101.), context(101.), now=11.)
        turned = reading(101.4, distance=None, bearing=.5)
        estimate.observe(turned, context(101.4), now=11.4)
        self.assertIsNone(estimate.hint(turned, now=11.5))
        straight = reading(101.5, distance=None)
        estimate.observe(straight, context(101.5, x=.30), now=11.5)
        self.assertIsNone(estimate.hint(straight, now=11.6))

        estimate.observe(straight, context(101.5, valid=False), now=11.6)
        self.assertIsNone(estimate.hint(straight, now=11.7))

    def test_new_metric_measurement_refreshes_anchor(self):
        estimate = MapFollowEstimate()
        estimate.observe(reading(100.), context(100.), now=10.)
        estimate.observe(reading(100.4, distance=2.4),
                         context(100.4, x=.1), now=10.4)
        self.assertAlmostEqual(estimate.anchor['x'], 2.68)
        self.assertGreater(estimate.anchor['velocity'][0], 0.)

    def test_no_fallback_if_metric_depth_source_disappears(self):
        estimate = MapFollowEstimate()
        estimate.observe(reading(100.), context(100.), now=10.)
        missing = reading(100.4, distance=None)
        missing['metric_depth_available'] = False
        estimate.observe(missing, context(100.4), now=10.4)
        self.assertIsNone(estimate.hint(missing, now=10.5))

    def test_single_missing_image_time_pose_keeps_only_fresh_anchor(self):
        estimate = MapFollowEstimate()
        estimate.observe(reading(100.), context(100.), now=10.)
        missing = reading(100.3, distance=None)
        estimate.observe(missing, context(100.3, valid=False), now=10.3)
        self.assertIsNotNone(estimate.anchor)
        self.assertIsNotNone(estimate.pose)
        self.assertIsNone(estimate.hint(missing, now=10.4))

    def test_nav_anchor_requires_independent_chest_corroboration(self):
        estimate = MapFollowEstimate(require_chest=True)
        observed = reading(100., distance=2.04)
        estimate.observe(observed, context(100.), now=10.)
        self.assertIsNone(estimate.anchor)
        observed['tracks'][0]['depth_diagnostic'] = dict(
            chest_reason='ok', chest_distance_m=2.05)
        estimate.observe(observed, context(100.), now=10.)
        self.assertIsNotNone(estimate.anchor)
        observed = reading(100.3, distance=1.53)
        observed['tracks'][0]['depth_diagnostic'] = dict(
            chest_reason='ok', chest_distance_m=2.04)
        estimate.observe(observed, context(100.3), now=10.3)
        self.assertAlmostEqual(estimate.anchor['x'], 2.22)

    def test_nav_anchor_rejects_dark_shirt_background_when_legs_disagree(self):
        estimate = MapFollowEstimate(require_chest=True)
        observed = reading(100., distance=2.1)
        observed['tracks'][0]['depth_diagnostic'] = dict(
            chest_reason='ok', chest_distance_m=2.1,
            lower_reason='ok', lower_distance_m=1.3,
            lower_pixels=900, lower_support=.96, lower_spread_m=.12)
        estimate.observe(observed, context(100.), now=10.)
        self.assertIsNone(estimate.anchor)

    def test_nav_anchor_uses_textured_legs_when_chest_has_no_depth(self):
        estimate = MapFollowEstimate(require_chest=True)
        observed = reading(100., distance=1.9)
        observed['tracks'][0]['depth_diagnostic'] = dict(
            chest_reason='insufficient_chest_depth',
            lower_reason='ok', lower_distance_m=1.84,
            lower_pixels=900, lower_support=.96, lower_spread_m=.12)
        estimate.observe(observed, context(100.), now=10.)
        self.assertIsNotNone(estimate.anchor)


if __name__ == '__main__':
    unittest.main()
