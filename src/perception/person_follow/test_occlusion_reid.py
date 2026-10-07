"""Session-only appearance evidence may recover a short selected-body gap.

These synthetic descriptors exercise the contract, not real ReID accuracy.
"""
import copy
import json
import math
import unittest

import numpy as np

from person_follow.tracking import ConservativeTracker


def person(box=(0, 0, 100, 200), score=.8, depth=2.):
    return dict(bbox=list(box), confidence=score, depth_m=depth)


def vector(cosine=1.):
    value = np.zeros(512, dtype=np.float32)
    value[0], value[1] = cosine, math.sqrt(max(0., 1.-cosine*cosine))
    return value


class OcclusionReidTests(unittest.TestCase):
    def seeded(self, selected=True, **options):
        tracker = ConservativeTracker(occlusion_reid=True, **options)
        track_id = tracker.update([person()], 0., {0: vector()})[0]['track_id']
        tracker.update([person()], .1, {0: vector()})
        if selected:
            tracker.select(track_id)
        return tracker, track_id

    def waiting(self):
        tracker, track_id = self.seeded()
        self.assertEqual(tracker.update([], .2, {}), [])
        self.assertEqual(tracker.last_events['selected_hold']['reason'], 'occlusion_reid_wait')
        return tracker, track_id

    def test_two_strong_adjacent_observations_establish_a_bounded_private_template(self):
        tracker, track_id = self.seeded()
        for index in range(2, 20):
            tracker.update([person()], index*.1, {0: vector()})
        self.assertEqual(len(tracker._appearance_templates[track_id]), 4)
        public = json.dumps(dict(tracks=list(tracker._tracks.values()), events=tracker.last_events))
        self.assertNotIn('embedding', public)
        self.assertNotIn('template', public)
        self.assertNotIn('recovery_proof', public)

    def test_one_strong_sighting_cannot_establish_recovery(self):
        tracker = ConservativeTracker(occlusion_reid=True)
        track_id = tracker.update([person()], 0., {0: vector()})[0]['track_id']
        tracker.select(track_id)
        tracker.update([], .1)
        self.assertEqual(tracker.last_events['selected_hold']['reason'], 'temporary_detection_miss')
        tracker.update([], .7)
        self.assertIsNone(tracker.selected_track_id)

    def test_wait_is_invisible_fixed_to_last_observation_and_eight_seconds(self):
        tracker, track_id = self.waiting()
        for now in (.3, 1., 2., 3., 7.9, 8.):
            self.assertEqual(tracker.update([], now), [])
            hold = tracker.last_events['selected_hold']
            self.assertEqual(hold['track_id'], track_id)
            self.assertEqual(hold['last_seen'], .1)
            self.assertEqual(hold['deadline_mono'], 8.1)
            self.assertAlmostEqual(hold['missing_age_s'], now-.1)
            for field in ('bbox', 'depth_m', 'identity', 'embedding'):
                self.assertNotIn(field, hold)
            self.assertNotIn(track_id, tracker._tracks)
        rows = tracker.update([person()], 8.11, {0: vector()})
        self.assertIsNone(tracker.selected_track_id)
        self.assertNotEqual(rows[0]['track_id'], track_id)
        self.assertEqual(tracker.last_events['occlusion_reid_reason'], 'occlusion_deadline_expired')

    def test_two_unique_fresh_strong_candidates_recover_same_id_with_proof_once(self):
        tracker, track_id = self.waiting()
        moved = person((35, 10, 140, 215), depth=2.2)
        self.assertEqual(tracker.update([moved], 1.5, {0: vector(.95)}), [])
        self.assertEqual(tracker.selected_track_id, track_id)
        rows = tracker.update([moved], 1.6, {0: vector(.94)})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['track_id'], track_id)
        self.assertEqual(rows[0]['depth_m'], 2.2)
        self.assertEqual(rows[0]['recovery_proof'], dict(
            track_id=track_id, episode_last_seen=.1, verified=True,
            method='appearance_geometry_unique', recovered_mono=1.6, candidate_count=1))
        self.assertIsNone(tracker.last_events['selected_hold'])
        rows = tracker.update([moved], 1.7, {0: vector(.94)})
        self.assertNotIn('recovery_proof', rows[0])

    def test_chair_occlusion_partial_boxes_can_wait_past_three_seconds(self):
        tracker, track_id = self.waiting()
        partial = person((15, 0, 100, 95), score=.7, depth=None)
        for now in (1., 2., 3.2, 4.2):
            self.assertEqual(tracker.update([partial], now, {0: vector(.2)}), [])
            self.assertEqual(tracker.selected_track_id, track_id)
            self.assertEqual(tracker.last_events['selected_hold']['reason'], 'occlusion_reid_wait')
        full = person((20, 0, 120, 200), depth=2.2)
        self.assertEqual(tracker.update([full], 4.4, {0: vector(.95)}), [])
        recovered = tracker.update([full], 4.6, {0: vector(.94)})
        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0]['track_id'], track_id)
        self.assertTrue(recovered[0]['recovery_proof']['verified'])

    def test_missing_embedding_never_restores_by_iou_and_resets_pending(self):
        tracker, track_id = self.waiting()
        self.assertEqual(tracker.update([person()], .3, {0: vector()}), [])
        self.assertEqual(tracker.update([person()], .4), [])
        self.assertEqual(tracker.update([person()], .5, {0: vector()}), [])
        rows = tracker.update([person()], .6, {0: vector()})
        self.assertEqual(rows[0]['track_id'], track_id)

    def test_missing_frame_or_long_gap_resets_two_frame_verification(self):
        for middle, when in (([], .4), ([person()], .8)):
            with self.subTest(middle=middle, when=when):
                tracker, track_id = self.waiting()
                self.assertEqual(tracker.update([person()], .3, {0: vector()}), [])
                self.assertEqual(tracker.update(middle, when, {0: vector()}), [])
                rows = tracker.update([person()], when+.1, {0: vector()})
                if not middle:
                    self.assertEqual(rows, [])
                    rows = tracker.update([person()], when+.2, {0: vector()})
                self.assertEqual(rows[0]['track_id'], track_id)

    def test_zero_nan_wrong_size_or_non_numeric_vectors_never_establish_template(self):
        for invalid in (np.zeros(512), [float('nan')]*512, [float('inf')]*512,
                        np.ones(511), 'bad', None):
            with self.subTest(value_type=type(invalid)):
                tracker = ConservativeTracker(occlusion_reid=True)
                track_id = tracker.update([person()], 0., {0: invalid})[0]['track_id']
                tracker.update([person()], .1, {0: invalid})
                tracker.select(track_id)
                tracker.update([], .2)
                self.assertNotIn(track_id, tracker._appearance_templates)
                self.assertEqual(tracker.last_events['selected_hold']['reason'], 'temporary_detection_miss')

    def test_bad_recovery_vector_cannot_bypass_confirmation(self):
        tracker, _ = self.waiting()
        for index, invalid in enumerate((np.zeros(512), [float('nan')]*512, np.ones(511))):
            self.assertEqual(tracker.update([person()], .3+index*.1, {0: invalid}), [])
            self.assertEqual(tracker.last_events['selected_hold']['last_seen'], .1)

    def test_appearance_mismatch_clears_selection_and_never_reuses_old_id(self):
        tracker, track_id = self.waiting()
        rows = tracker.update([person()], .3, {0: vector(.3)})
        self.assertIsNone(tracker.selected_track_id)
        self.assertNotEqual(rows[0]['track_id'], track_id)
        self.assertEqual(tracker.last_events['occlusion_reid_reason'], 'appearance_mismatch')

    def test_chair_cropped_body_waits_instead_of_clearing_identity(self):
        tracker, track_id = self.waiting()
        partial = person((0, 0, 100, 90), score=.55, depth=None)
        for now in (.3, .4):
            self.assertEqual(tracker.update([partial], now, {0: vector(.3)}), [])
            self.assertEqual(tracker.selected_track_id, track_id)
            self.assertEqual(tracker.last_events['selected_hold']['reason'],
                             'occlusion_reid_wait')
            self.assertNotEqual(tracker.last_events['occlusion_reid_reason'],
                                'appearance_mismatch')
        self.assertEqual(tracker.update([person()], .5, {0: vector(.95)}), [])
        restored = tracker.update([person()], .6, {0: vector(.95)})
        self.assertEqual(restored[0]['track_id'], track_id)
        self.assertTrue(restored[0]['recovery_proof']['verified'])

    def test_partial_body_with_matching_clothes_cannot_claim_identity(self):
        tracker, track_id = self.waiting()
        partial = person((0, 0, 100, 90), score=.9, depth=None)
        for now in (.3, .4, .5):
            self.assertEqual(tracker.update([partial], now, {0: vector()}), [])
        self.assertEqual(tracker.selected_track_id, track_id)
        self.assertEqual(tracker.last_events['selected_hold']['last_seen'], .1)

    def test_two_similar_candidates_cancel_instead_of_choosing_by_iou(self):
        tracker, track_id = self.waiting()
        rows = tracker.update([person(), person((70, 0, 170, 200))], .3,
                              {0: vector(.95), 1: vector(.91)})
        self.assertIsNone(tracker.selected_track_id)
        self.assertNotIn(track_id, [row['track_id'] for row in rows])
        self.assertEqual(tracker.last_events['occlusion_reid_reason'], 'recovery_candidates_ambiguous')

    def test_runner_up_with_unavailable_embedding_blocks_recovery(self):
        tracker, _ = self.waiting()
        for now in (.3, .4, .5):
            self.assertEqual(tracker.update([person(), person((70, 0, 170, 200))], now,
                                            {0: vector()}), [])
            self.assertEqual(tracker.last_events['occlusion_reid_reason'], 'embedding_unavailable')

    def test_unselected_missing_track_does_not_receive_three_second_identity_hold(self):
        tracker, track_id = self.seeded(selected=False)
        tracker.update([], .2)
        self.assertIsNone(tracker._occlusion_episode)
        tracker.update([], 1.)
        rows = tracker.update([person()], 1.1, {0: vector()})
        self.assertNotEqual(rows[0]['track_id'], track_id)

    def test_unlock_and_reset_discard_private_wait_and_do_not_recover(self):
        for action in ('clear_selection', 'reset'):
            with self.subTest(action=action):
                tracker, track_id = self.waiting()
                getattr(tracker, action)()
                self.assertIsNone(tracker._occlusion_episode)
                self.assertNotIn(track_id, tracker._appearance_templates)
                rows = tracker.update([person()], .3, {0: vector()})
                self.assertNotEqual(rows[0]['track_id'], track_id)
                self.assertIsNone(tracker.selected_track_id)

    def test_nonmonotonic_clock_resets_wait(self):
        tracker, track_id = self.waiting()
        rows = tracker.update([person()], .1, {0: vector()})
        self.assertNotEqual(rows[0]['track_id'], track_id)
        self.assertIsNone(tracker._occlusion_episode)

    def test_template_expires_even_when_geometry_continues_without_new_embeddings(self):
        tracker, track_id = self.seeded()
        for index in range(2, 104):
            tracker.update([person()], index*.1)
        tracker.update([], 10.4)
        self.assertNotIn(track_id, tracker._appearance_templates)
        self.assertEqual(tracker.last_events['selected_hold']['reason'], 'temporary_detection_miss')

    def test_weak_candidates_cannot_recover_or_extend_wait(self):
        tracker, _ = self.waiting()
        for now in (.3, .4, 1., 2.):
            self.assertEqual(tracker.update([person(score=.4)], now, {0: vector()}), [])
            self.assertEqual(tracker.last_events['selected_hold']['last_seen'], .1)
        tracker.update([person(score=.4)], 8.2, {0: vector()})
        self.assertIsNone(tracker.selected_track_id)

    def test_wrong_geometry_scale_depth_or_position_never_recovers_original_id(self):
        invalids = [person(depth=3.), person((200, 0, 300, 200)),
                    person((0, 0, 250, 200)), person((0, 0, 100, 40))]
        for candidate in invalids:
            with self.subTest(candidate=candidate):
                tracker, track_id = self.waiting()
                for now in (.3, .4):
                    rows = tracker.update([candidate], now, {0: vector()})
                    self.assertNotIn(track_id, [row['track_id'] for row in rows])

    def test_never_borrows_old_depth_after_recovery(self):
        tracker, track_id = self.waiting()
        tracker.update([person(depth=None)], .3, {0: vector()})
        row = tracker.update([person(depth=None)], .4, {0: vector()})[0]
        self.assertEqual(row['track_id'], track_id)
        self.assertIsNone(row['depth_m'])

    def test_unrelated_person_can_remain_visible_while_selected_person_waits(self):
        tracker, track_id = self.waiting()
        other = person((500, 0, 600, 200))
        rows = tracker.update([other], .3, {0: vector(.1)})
        other_id = rows[0]['track_id']
        self.assertNotEqual(other_id, track_id)
        self.assertEqual(tracker.selected_track_id, track_id)
        rows = tracker.update([other, person()], .4, {0: vector(.1), 1: vector()})
        self.assertEqual([row['track_id'] for row in rows], [other_id])
        rows = tracker.update([other, person()], .5, {0: vector(.1), 1: vector()})
        self.assertEqual({row['track_id'] for row in rows}, {other_id, track_id})

    def test_preexisting_other_track_ownership_cannot_be_stolen(self):
        tracker = ConservativeTracker(occlusion_reid=True)
        other = person((160, 0, 260, 200))
        first = tracker.update([person(), other], 0., {0: vector(), 1: vector(.9)})
        track_id, other_id = [row['track_id'] for row in first]
        tracker.update([person(), other], .1, {0: vector(), 1: vector(.9)})
        tracker.select(track_id)
        tracker.update([other], .2, {0: vector(.9)})
        self.assertIsNotNone(tracker._occlusion_episode)
        rows = tracker.update([person((120, 0, 220, 200))], .3, {0: vector()})
        self.assertIsNone(tracker.selected_track_id)
        self.assertEqual(rows[0]['track_id'], other_id)
        self.assertEqual(tracker.last_events['occlusion_reid_reason'], 'candidate_has_other_track')

    def test_original_inputs_and_embeddings_are_not_mutated(self):
        tracker, _ = self.seeded()
        detections = [person()]
        original = copy.deepcopy(detections)
        descriptor = vector()
        descriptor_copy = descriptor.copy()
        tracker.update(detections, .2, {0: descriptor})
        self.assertEqual(detections, original)
        np.testing.assert_array_equal(descriptor, descriptor_copy)

    def test_default_off_does_not_establish_reid_state(self):
        tracker = ConservativeTracker()
        track_id = tracker.update([person()], 0., {0: vector()})[0]['track_id']
        tracker.update([person()], .1, {0: vector()})
        tracker.select(track_id)
        tracker.update([], .2, {})
        self.assertEqual(tracker._appearance_templates, {})
        self.assertEqual(tracker.last_events['selected_hold']['reason'], 'temporary_detection_miss')

    def test_readiness_exposes_only_boolean_and_tracks_fresh_template_lifetime(self):
        tracker = ConservativeTracker(occlusion_reid=True)
        track_id = tracker.update([person()], 0., {0: vector()})[0]['track_id']
        self.assertFalse(tracker.recovery_ready(track_id, 0.))
        tracker.update([person()], .1, {0: vector()})
        self.assertIs(tracker.recovery_ready(track_id, .1), True)
        self.assertFalse(tracker.recovery_ready(None, .1))
        self.assertFalse(tracker.recovery_ready(9999, .1))
        self.assertFalse(tracker.recovery_ready(track_id, float('nan')))
        tracker.select(track_id)
        tracker.update([], .2)
        self.assertIs(tracker.recovery_ready(track_id, 2.), True)
        self.assertFalse(tracker.recovery_ready(track_id, 8.2))
        tracker.clear_selection()
        self.assertFalse(tracker.recovery_ready(track_id, .3))

    def test_no_template_keeps_existing_short_hold_semantics_only(self):
        tracker = ConservativeTracker(occlusion_reid=True)
        track_id = tracker.update([person()], 0.)[0]['track_id']
        tracker.select(track_id)
        tracker.update([], .1)
        self.assertEqual(tracker.last_events['selected_hold']['reason'], 'temporary_detection_miss')
        self.assertFalse(tracker.recovery_ready(track_id, .1))
        rows = tracker.update([person()], .2)
        self.assertEqual(rows[0]['track_id'], track_id)
        self.assertNotIn('recovery_proof', rows[0])


if __name__ == '__main__':
    unittest.main()
