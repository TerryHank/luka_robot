import unittest

from person_follow.tracking import ConservativeTracker


def person(box=(0, 0, 100, 200), score=.8, depth=2.):
    return dict(bbox=list(box), confidence=score, depth_m=depth)


class TrackingStageTests(unittest.TestCase):
    def selected(self, **options):
        tracker = ConservativeTracker(**options)
        track_id = tracker.update([person()], 0)[0]['track_id']
        tracker.select(track_id)
        return tracker, track_id

    def test_strong_match_with_weak_upper_body_duplicate_keeps_one_id(self):
        for reverse in (False, True):
            tracker, track_id = self.selected()
            detections = [person(), person((5, 0, 95, 100), .25)]
            if reverse:
                detections.reverse()
            for now in (.1, .2, .3):
                tracks = tracker.update(detections, now)
                self.assertEqual(len(tracks), 1)
                self.assertEqual(tracks[0]['track_id'], track_id)
                self.assertEqual(tracks[0]['observation_strength'], 'strong')
                self.assertFalse(tracks[0]['association_ambiguous'])
                self.assertFalse(tracker.last_events['ambiguous'])
                self.assertEqual(tracker.selected_track_id, track_id)

    def test_weak_runner_up_cannot_poison_strong_match(self):
        tracker, track_id = self.selected()
        tracks = tracker.update([person((1, 0, 101, 200)), person((2, 0, 102, 200), .3)], .1)
        self.assertEqual([t['track_id'] for t in tracks], [track_id])
        self.assertFalse(tracker.last_events['ambiguous'])

    def test_independent_second_track_can_continue_weak_while_duplicate_is_ignored(self):
        tracker = ConservativeTracker()
        original = tracker.update([person(), person((300, 0, 400, 200))], 0)
        first, second = [t['track_id'] for t in original]
        tracker.select(second)
        result = tracker.update([person(), person((5, 0, 95, 100), .25),
                                 person((303, 0, 403, 200), .25)], .1)
        self.assertEqual([t['track_id'] for t in result], [first, second])
        self.assertEqual([t['observation_strength'] for t in result], ['strong', 'weak'])
        self.assertEqual(tracker.selected_track_id, second)
        self.assertFalse(tracker.last_events['ambiguous'])

    def test_weak_cannot_steal_track_already_assigned_to_strong(self):
        tracker, track_id = self.selected()
        result = tracker.update([person((25, 0, 125, 200), .8), person(score=.3)], .1)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['bbox'], [25., 0., 125., 200.])
        self.assertEqual(result[0]['track_id'], track_id)
        self.assertEqual(result[0]['observation_strength'], 'strong')

    def test_real_strong_crossing_still_retires_old_ids(self):
        tracker = ConservativeTracker()
        old = tracker.update([person(), person((140, 0, 240, 200))], 0)
        ids = {t['track_id'] for t in old}
        tracker.select(old[0]['track_id'])
        result = tracker.update([person((55, 0, 155, 200)), person((80, 0, 180, 200))], .1)
        self.assertTrue(tracker.last_events['ambiguous'])
        self.assertIsNone(tracker.selected_track_id)
        self.assertTrue(ids.isdisjoint(t['track_id'] for t in result))
        self.assertTrue(all(t['association_ambiguous'] for t in result))

    def test_unselected_weak_only_ambiguity_retires_without_creating_new_people(self):
        tracker, track_id = self.selected()
        tracker.clear_selection()
        result = tracker.update([person((1, 0, 101, 200), .3), person((-1, 0, 99, 200), .31)], .1)
        self.assertEqual(result, [])
        self.assertTrue(tracker.last_events['ambiguous'])
        self.assertIn(track_id, tracker.last_events['retired_ids'])
        self.assertIsNone(tracker.selected_track_id)

    @staticmethod
    def ambiguous_weak():
        return [person((1, 0, 101, 200), .3), person((-1, 0, 99, 200), .31)]

    def test_selected_sole_weak_tie_waits_without_emitting_either_candidate(self):
        tracker, track_id = self.selected()
        self.assertEqual(tracker.update(self.ambiguous_weak(), .1), [])
        self.assertEqual(tracker.selected_track_id, track_id)
        self.assertNotIn(track_id, tracker.last_events['retired_ids'])
        hold = tracker.last_events['selected_hold']
        self.assertEqual(hold['reason'], 'temporary_detection_miss')
        self.assertEqual(tracker.last_events['hold_diagnostic_reason'], 'weak_runner_up_waiting_for_strong')
        self.assertEqual(hold['last_seen'], 0)
        self.assertAlmostEqual(hold['missing_age_s'], .1)
        for key in ('bbox', 'depth_m', 'distance_m', 'bearing_rad', 'identity'):
            self.assertNotIn(key, hold)
        with self.assertRaises(ValueError):
            tracker.select(track_id)

    def test_single_weak_candidate_cannot_resolve_or_extend_ambiguous_wait(self):
        tracker, track_id = self.selected()
        tracker.update(self.ambiguous_weak(), .1)
        for now in (.2, .4, .59):
            self.assertEqual(tracker.update([person(score=.4)], now), [])
            self.assertEqual(tracker.selected_track_id, track_id)
            self.assertEqual(tracker.last_events['selected_hold']['last_seen'], 0)
            self.assertAlmostEqual(tracker.last_events['selected_hold']['missing_age_s'], now)
            self.assertEqual(tracker._tracks[track_id]['last_seen'], 0)
        self.assertEqual(tracker.update([person(score=.4)], .61), [])
        self.assertIsNone(tracker.selected_track_id)
        self.assertNotIn(track_id, tracker._tracks)

    def test_unambiguous_strong_within_wait_restores_same_id_and_fresh_geometry(self):
        tracker, track_id = self.selected()
        tracker.update(self.ambiguous_weak(), .1)
        tracker.update([person(score=.4)], .2)
        result = tracker.update([person((3, 0, 103, 200), .7, 2.1)], .4)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['track_id'], track_id)
        self.assertEqual(result[0]['bbox'], [3., 0., 103., 200.])
        self.assertEqual(result[0]['depth_m'], 2.1)
        self.assertNotIn('_awaiting_strong', result[0])
        self.assertEqual(tracker.selected_track_id, track_id)
        self.assertIsNone(tracker.last_events['selected_hold'])

    def test_strong_outside_geometry_or_depth_gates_cancels_wait(self):
        for candidate in (person((400, 0, 500, 200)), person(depth=4.)):
            tracker, track_id = self.selected()
            tracker.update(self.ambiguous_weak(), .1)
            result = tracker.update([candidate], .2)
            self.assertEqual(len(result), 1)
            self.assertNotEqual(result[0]['track_id'], track_id)
            self.assertIsNone(tracker.selected_track_id)
            self.assertIsNone(tracker.last_events['selected_hold'])

    def test_strong_ambiguity_cancels_wait_instead_of_picking_one(self):
        tracker, track_id = self.selected()
        tracker.update(self.ambiguous_weak(), .1)
        result = tracker.update([person((1, 0, 101, 200)), person((-1, 0, 99, 200))], .2)
        self.assertEqual(len(result), 2)
        self.assertTrue(all(row['association_ambiguous'] for row in result))
        self.assertIn(track_id, tracker.last_events['retired_ids'])
        self.assertIsNone(tracker.selected_track_id)

    def test_another_historical_id_prevents_special_weak_wait(self):
        tracker = ConservativeTracker()
        original = tracker.update([person(), person((400, 0, 500, 200))], 0)
        tracker.select(original[0]['track_id'])
        self.assertEqual(tracker.update(self.ambiguous_weak(), .1), [])
        self.assertIsNone(tracker.selected_track_id)
        self.assertIsNone(tracker.last_events['selected_hold'])

    def test_expired_wait_never_restores_old_id_even_with_long_general_retention(self):
        tracker, track_id = self.selected(max_missing_s=2.)
        tracker.update(self.ambiguous_weak(), .1)
        result = tracker.update([person()], .61)
        self.assertNotEqual(result[0]['track_id'], track_id)
        self.assertIsNone(tracker.selected_track_id)
        self.assertIsNone(tracker.last_events['selected_hold'])

    def test_wait_anchor_is_last_observation_not_first_ambiguous_frame(self):
        tracker, track_id = self.selected()
        tracker.update([person(score=.3)], .2)
        tracker.update(self.ambiguous_weak(), .4)
        self.assertAlmostEqual(tracker.last_events['selected_hold']['last_seen'], .2)
        self.assertEqual(tracker.update([], .79), [])
        self.assertEqual(tracker.selected_track_id, track_id)
        self.assertEqual(tracker.update([], .81), [])
        self.assertIsNone(tracker.selected_track_id)

    def test_sole_old_person_with_clear_weak_winner_ignores_overlapping_weak_ghost(self):
        tracker = ConservativeTracker()
        real_box = (136, 58, 384, 379)
        track_id = tracker.update([person(real_box, .8, 1.194)], 0)[0]['track_id']
        tracker.select(track_id)
        result = tracker.update([person(real_box, .4019, 1.194),
                                 person((2, 2, 352, 446), .2815, None)], .1)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['track_id'], track_id)
        self.assertEqual(result[0]['bbox'], list(real_box))
        self.assertEqual(tracker.selected_track_id, track_id)
        self.assertFalse(tracker.last_events['ambiguous'])

    def test_two_historical_people_still_cannot_continue_through_weak_overlap(self):
        tracker = ConservativeTracker()
        original = tracker.update([person(), person((140, 0, 240, 200))], 0)
        tracker.select(original[0]['track_id'])
        result = tracker.update([person((35, 0, 135, 200), .3),
                                 person((80, 0, 180, 200), .31)], .1)
        self.assertEqual(result, [])
        self.assertTrue(tracker.last_events['ambiguous'])
        self.assertIsNone(tracker.selected_track_id)

    def test_new_weak_detections_do_not_create_tracks_or_ambiguity(self):
        tracker = ConservativeTracker()
        result = tracker.update([person(score=.25), person((5, 0, 95, 100), .3)], 0)
        self.assertEqual(result, [])
        self.assertFalse(tracker.last_events['ambiguous'])

    def test_far_weak_junk_allows_bounded_invisible_hold_without_refreshing_age(self):
        tracker, track_id = self.selected()
        far_weak = person((500, 0, 600, 200), .25)
        for now in (.1, .3, .55):
            self.assertEqual(tracker.update([far_weak], now), [])
            self.assertEqual(tracker.selected_track_id, track_id)
            self.assertAlmostEqual(tracker.last_events['selected_hold']['missing_age_s'], now)
        self.assertEqual(tracker.update([far_weak], .61), [])
        self.assertIsNone(tracker.selected_track_id)
        self.assertIsNone(tracker.last_events['selected_hold'])

    def test_any_competing_strong_candidate_ends_hold_even_if_unmatched(self):
        tracker, track_id = self.selected()
        result = tracker.update([person((500, 0, 600, 200)), person((800, 0, 900, 200), .2)], .1)
        self.assertEqual(len(result), 1)
        self.assertNotEqual(result[0]['track_id'], track_id)
        self.assertIsNone(tracker.selected_track_id)

    def test_near_weak_failing_depth_gate_does_not_justify_a_hold(self):
        tracker, _ = self.selected()
        self.assertEqual(tracker.update([person(score=.25, depth=4.)], .1), [])
        self.assertIsNone(tracker.selected_track_id)
        self.assertIsNone(tracker.last_events['selected_hold'])

    def test_weak_continuation_timeout_remains_enforced(self):
        tracker, track_id = self.selected(max_weak_s=.5)
        for now in (.1, .3, .49):
            self.assertEqual(tracker.update([person(score=.25)], now)[0]['track_id'], track_id)
        self.assertEqual(tracker.update([person(score=.25)], .51), [])
        self.assertIsNone(tracker.selected_track_id)

    def test_weak_at_separate_depth_does_not_get_suppressed_by_strong(self):
        tracker = ConservativeTracker()
        old = tracker.update([person(depth=1.), person(depth=2.)], 0)
        old_ids = [t['track_id'] for t in old]
        self.assertFalse(tracker.last_events['ambiguous'])
        result = tracker.update([person(depth=1.), person(score=.25, depth=2.)], .1)
        self.assertEqual([t['track_id'] for t in result], old_ids)

    def test_unique_fresh_moderate_observations_do_not_expire_only_for_lack_of_strong_score(self):
        tracker, track_id = self.selected()
        for index in range(1, 81):
            now = index * .125
            result = tracker.update([person(score=.35, depth=None)], now)
            self.assertEqual(len(result), 1)
            row = result[0]
            self.assertEqual(row['track_id'], track_id)
            self.assertEqual(row['observation_strength'], 'weak')
            self.assertEqual(row['last_strong_seen'], 0)
            self.assertEqual(row['last_seen'], now)
            self.assertIsNone(row['depth_m'])
            self.assertEqual(tracker.selected_track_id, track_id)
            if index >= 2:
                self.assertEqual(row['continuity_evidence'], 'stable_moderate_observation')
                self.assertEqual(row['last_reliable_body_seen'], now)
        # Better body continuity does not qualify a weak frame for selection,
        # and worker enrollment/face matching uses this same strength field.
        with self.assertRaises(ValueError):
            tracker.select(track_id)

    def test_stable_unselected_moderate_person_does_not_flicker_ids(self):
        tracker = ConservativeTracker()
        track_id = tracker.update([person()], 0)[0]['track_id']
        for index in range(1, 41):
            result = tracker.update([person(score=.38)], index*.125)
            self.assertEqual(result[0]['track_id'], track_id)
        self.assertIsNone(tracker.selected_track_id)

    def test_real_event_upper_and_full_body_changes_keep_top_anchor_without_inventing_depth(self):
        tracker = ConservativeTracker()
        first = person((147, 60, 361, 264), .51, None)
        track_id = tracker.update([first], 0)[0]['track_id']
        tracker.select(track_id)
        candidates = [person((148, 60, 361, 260), .3406, None),
                      person((142, 61, 400, 452), .3503, 1.072),
                      person((147, 60, 361, 264), .3748, None)]
        for index in range(1, 49):
            candidate = candidates[index % len(candidates)]
            result = tracker.update([candidate], index*.125)
            self.assertEqual(result[0]['track_id'], track_id)
            self.assertEqual(result[0]['depth_m'], candidate['depth_m'])
            self.assertEqual(result[0]['observation_strength'], 'weak')

    def test_reliable_body_clock_needs_three_adjacent_quality_observations(self):
        tracker, _ = self.selected()
        row = tracker.update([person(score=.35)], .1)[0]
        self.assertEqual(row['last_reliable_body_seen'], 0)
        tracker.update([person(score=.25)], .2)
        for now in (.3, .4):
            row = tracker.update([person(score=.35)], now)[0]
            self.assertEqual(row['last_reliable_body_seen'], 0)
        row = tracker.update([person(score=.35)], .5)[0]
        self.assertEqual(row['last_reliable_body_seen'], .5)
        self.assertEqual(row['last_strong_seen'], 0)

    def test_missing_processed_frames_cannot_supply_moderate_continuity_proof(self):
        tracker, _ = self.selected()
        for index in range(1, 14):
            now = index*.1
            result = tracker.update([person(score=.35)] if index % 2 else [], now)
            if result:
                self.assertEqual(result[0]['last_reliable_body_seen'], 0)
        self.assertEqual(tracker.update([person(score=.35)], 1.5), [])
        self.assertIsNone(tracker.selected_track_id)

    def test_moderate_top_anchor_jumps_do_not_get_unlimited_continuation(self):
        tracker, _ = self.selected()
        for index in range(1, 14):
            offset = 0 if index % 2 else 30
            result = tracker.update([person((0, offset, 100, 200+offset), .35)], index*.1)
            if result:
                self.assertEqual(result[0]['last_reliable_body_seen'], 0)
        self.assertIsNone(tracker.selected_track_id)

    def test_two_people_do_not_receive_the_single_body_moderate_exemption(self):
        tracker = ConservativeTracker()
        original = tracker.update([person(), person((400, 0, 500, 200))], 0)
        first_id = original[0]['track_id']
        tracker.select(first_id)
        for index in range(1, 14):
            result = tracker.update([person(score=.35), person((400, 0, 500, 200))], index*.1)
            for row in result:
                if row['track_id'] == first_id:
                    self.assertEqual(row['last_reliable_body_seen'], 0)
        self.assertIsNone(tracker.selected_track_id)

    def test_low_score_duration_remains_bounded_after_reliable_moderate_observations(self):
        tracker, track_id = self.selected()
        for index in range(1, 21):
            tracker.update([person(score=.35)], index*.1)
        for index in range(21, 31):
            result = tracker.update([person(score=.25)], index*.1)
            self.assertEqual(result[0]['track_id'], track_id)
            self.assertAlmostEqual(result[0]['last_reliable_body_seen'], 2.)
        self.assertEqual(tracker.update([person(score=.25)], 3.21), [])
        self.assertIsNone(tracker.selected_track_id)

    def test_absence_after_sustained_moderate_is_still_a_fixed_short_invisible_wait(self):
        tracker, track_id = self.selected()
        for index in range(1, 21):
            tracker.update([person(score=.35)], index*.1)
        for now in (2.1, 2.3, 2.59):
            self.assertEqual(tracker.update([], now), [])
            self.assertEqual(tracker.selected_track_id, track_id)
            self.assertEqual(tracker.last_events['selected_hold']['last_seen'], 2.)
        self.assertEqual(tracker.update([], 2.61), [])
        self.assertIsNone(tracker.selected_track_id)

    def test_moderate_depth_jump_can_match_briefly_but_cannot_refresh_reliable_clock(self):
        tracker, _ = self.selected()
        for index in range(1, 14):
            depth = 2. if index % 2 else 2.3
            result = tracker.update([person(score=.35, depth=depth)], index*.1)
            if result:
                self.assertEqual(result[0]['last_reliable_body_seen'], 0)
        self.assertIsNone(tracker.selected_track_id)

    def test_moderate_cannot_break_require_strong_wait_even_if_it_was_previously_sustained(self):
        tracker, _ = self.selected()
        for index in range(1, 21):
            tracker.update([person(score=.35)], index*.1)
        self.assertEqual(tracker.update(self.ambiguous_weak(), 2.1), [])
        for now in (2.2, 2.4, 2.59):
            self.assertEqual(tracker.update([person(score=.4)], now), [])
            self.assertEqual(tracker.last_events['selected_hold']['last_seen'], 2.)
        self.assertEqual(tracker.update([person(score=.4)], 2.61), [])
        self.assertIsNone(tracker.selected_track_id)


if __name__ == '__main__':
    unittest.main()
