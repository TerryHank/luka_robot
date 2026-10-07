"""Temporal range safety around intermittent stereo/foreground layers."""
import unittest

from person_range_gate import PersonRangeGate


def reading(at, distance, *, track_id=3, valid=True, active=True):
    return dict(frame_at=at,
                target_session=dict(active=active, visible=active,
                                    face_verified=active, profile_id='owner',
                                    track_id=track_id),
                tracks=[dict(track_id=track_id, selected=True, depth_valid=valid,
                             distance_m=distance, bbox=[220, 80, 390, 420])])


class PersonRangeGateTest(unittest.TestCase):
    def test_requires_two_distinct_metric_frames(self):
        gate = PersonRangeGate()
        self.assertFalse(gate.protect(reading(100., 2.))['tracks'][0]['depth_valid'])
        self.assertFalse(gate.protect(reading(100., 2.))['tracks'][0]['depth_valid'])
        self.assertTrue(gate.protect(reading(100.2, 2.03))['tracks'][0]['depth_valid'])

    def test_interleaved_missing_frames_allow_only_matching_static_range(self):
        gate = PersonRangeGate()
        gate.protect(reading(100., 2.04))
        gate.protect(reading(100.3, None, valid=False))
        self.assertTrue(gate.protect(reading(101.2, 2.05))['tracks'][0]['depth_valid'])

    def test_different_furniture_layer_cannot_complete_pending_range(self):
        gate = PersonRangeGate()
        gate.protect(reading(100., 2.04))
        gate.protect(reading(100.3, None, valid=False))
        self.assertFalse(gate.protect(reading(100.8, 1.53))['tracks'][0]['depth_valid'])

    def test_one_strong_chest_measurement_can_seed_nav_but_not_furniture(self):
        gate = PersonRangeGate(single_chest=True)
        observed = reading(100., 2.04)
        observed['tracks'][0]['depth_diagnostic'] = dict(
            chest_reason='ok', chest_distance_m=2.05,
            chest_pixels=430, chest_support=.95, chest_spread_m=.13)
        self.assertTrue(gate.protect(observed)['tracks'][0]['depth_valid'])
        mixed = reading(100.2, 1.53)
        mixed['tracks'][0]['depth_diagnostic'] = dict(
            chest_reason='ok', chest_distance_m=2.04,
            chest_pixels=430, chest_support=.95, chest_spread_m=.13)
        self.assertFalse(gate.protect(mixed)['tracks'][0]['depth_valid'])

    def test_unverified_single_chest_cannot_seed_nav(self):
        gate = PersonRangeGate(single_chest=True)
        observed = reading(100., 2.04)
        observed['target_session']['face_verified'] = False
        observed['tracks'][0]['depth_diagnostic'] = dict(
            chest_reason='ok', chest_distance_m=2.05,
            chest_pixels=430, chest_support=.95, chest_spread_m=.13)
        gate.protect(observed)
        self.assertEqual(gate.reason, 'target_not_verified')

    def test_single_furniture_jump_is_rejected_and_recovers(self):
        gate = PersonRangeGate()
        gate.protect(reading(100., 2.))
        gate.protect(reading(100.2, 2.01))
        self.assertFalse(gate.protect(reading(100.4, .73))['tracks'][0]['depth_valid'])
        self.assertTrue(gate.protect(reading(100.6, 2.04))['tracks'][0]['depth_valid'])

    def test_real_large_change_needs_two_consistent_frames(self):
        gate = PersonRangeGate()
        gate.protect(reading(100., 2.))
        gate.protect(reading(100.2, 2.01))
        self.assertFalse(gate.protect(reading(100.4, 3.1))['tracks'][0]['depth_valid'])
        self.assertTrue(gate.protect(reading(100.6, 3.13))['tracks'][0]['depth_valid'])

    def test_no_distance_is_not_bridged(self):
        gate = PersonRangeGate()
        gate.protect(reading(100., 2.))
        gate.protect(reading(100.2, 2.01))
        self.assertFalse(gate.protect(reading(100.4, None, valid=False))['tracks'][0]['depth_valid'])

    def test_new_person_cannot_borrow_old_range(self):
        gate = PersonRangeGate()
        gate.protect(reading(100., 2.))
        gate.protect(reading(100.2, 2.01))
        self.assertFalse(gate.protect(reading(100.4, 2.0, track_id=4))['tracks'][0]['depth_valid'])
        self.assertTrue(gate.protect(reading(100.6, 2.03, track_id=4))['tracks'][0]['depth_valid'])

    def test_unverified_target_clears_history(self):
        gate = PersonRangeGate()
        gate.protect(reading(100., 2.))
        gate.protect(reading(100.2, 2.01))
        gate.protect(reading(100.4, None, active=False, valid=False))
        self.assertFalse(gate.protect(reading(100.6, 2.))['tracks'][0]['depth_valid'])


if __name__ == '__main__':
    unittest.main()
