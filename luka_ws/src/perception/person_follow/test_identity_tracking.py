"""Run: python -m unittest person_follow.test_identity_tracking -v."""
import tempfile
import unittest
from pathlib import Path

import numpy as np

from person_follow.identity import EnrollmentManager, IdentityRecognizer, IdentityStore, normalized_embedding
from person_follow.tracking import ConservativeTracker


def face(axis=0, perturbation=0.0, side=2):
    value = np.zeros(128, dtype=np.float32)
    value[axis] = 1.0
    value[side] += perturbation
    return normalized_embedding(value)


def samples(axis=0):
    return [face(axis, v) for v in (-0.08, 0, 0.08)]


def person(x, depth=2.0, width=30):
    return dict(bbox=[x, 0, x + width, 80], depth_m=depth, confidence=0.9)


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.store = IdentityStore(":memory:")

    def tearDown(self):
        self.store.close()

    def test_profile_persists_and_delete_removes_samples(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "identities.sqlite3"
            first = IdentityStore(path)
            saved = first.add_profile("露卡测试", samples())
            first.close()
            reopened = IdentityStore(path)
            self.assertEqual(reopened.list_profiles()[0]["sample_count"], 3)
            self.assertEqual(reopened.match(face())["profile_id"], saved["id"])
            self.assertTrue(reopened.delete_profile(saved["id"]))
            self.assertEqual(reopened.match(face())["reason"], "no_profiles")
            reopened.close()

    def test_duplicate_name_never_overwrites(self):
        self.store.add_profile("Alice", samples())
        with self.assertRaises(ValueError):
            self.store.add_profile("alice", samples(1))
        self.assertEqual(len(self.store.list_profiles()), 1)
        with self.assertRaises(ValueError):
            self.store.add_profile("bad\nname", samples())
        with self.assertRaises(ValueError):
            self.store.add_profile(None, samples())

    def test_unknown_and_ambiguous_face_are_not_names(self):
        self.store.add_profile("A", samples())
        unknown = self.store.match(face(1))
        self.assertFalse(unknown["known"])
        self.assertEqual(unknown["reason"], "low_similarity")
        self.store.add_profile("Similar B", [face(0, v, side=3) for v in (-0.08, 0, 0.08)])
        ambiguous = self.store.match(face())
        self.assertFalse(ambiguous["known"])
        self.assertIsNone(ambiguous["profile_id"])
        self.assertEqual(ambiguous["reason"], "ambiguous_identity")

    def test_multiframe_confirmation_and_mismatch_revocation(self):
        self.store.add_profile("A", samples())
        self.store.add_profile("B", samples(1))
        recognizer = IdentityRecognizer(self.store)
        self.assertFalse(recognizer.observe(1, face(), 1)["known"])
        self.assertFalse(recognizer.observe(1, face(), 1.1)["known"])
        self.assertEqual(recognizer.observe(1, face(), 1.2)["name"], "A")
        mismatch = recognizer.observe(1, face(1), 1.3)
        self.assertFalse(mismatch["known"])
        self.assertIsNone(mismatch["name"])
        self.assertEqual(mismatch["confirmations"], 1)
        recognizer.observe(1, face(1), 1.4)
        self.assertTrue(recognizer.observe(1, face(1), 1.5)["known"])
        self.assertFalse(recognizer.observe(1, face(3), 1.6)["known"])

    def test_gap_duplicate_frame_and_prune_cannot_preserve_confirmation(self):
        self.store.add_profile("A", samples())
        recognizer = IdentityRecognizer(self.store, max_gap_s=0.5)
        recognizer.observe(7, face(), 1)
        self.assertEqual(recognizer.observe(7, face(), 1)["confirmations"], 1)
        recognizer.observe(7, face(), 1.1)
        self.assertFalse(recognizer.observe(7, face(), 2)["known"])
        recognizer.prune([])
        self.assertEqual(recognizer.observe(7, face(), 2.1)["confirmations"], 1)
        self.assertEqual(recognizer.observe(8, face(), 2.2)["confirmations"], 1)

    def test_invalid_vectors_rejected(self):
        for value in [np.zeros(128), np.full(128, np.nan), np.zeros(127)]:
            with self.assertRaises(ValueError):
                self.store.match(value)

    def test_enrollment_is_explicit_bounded_and_duplicate_aware(self):
        enrollment = EnrollmentManager(self.store, target=3)
        enrollment.start("A", 9, 0)
        self.assertEqual(enrollment.add_sample(9, face(), now=0)["samples"], 1)
        repeated = enrollment.add_sample(9, face(), now=0.3)
        self.assertEqual(repeated["reason"], "duplicate_sample")
        self.assertEqual(repeated["samples"], 1)
        enrollment.add_sample(9, face(0, 0.08), now=0.6)
        self.assertEqual(enrollment.add_sample(9, face(0, -0.08), now=0.9)["state"], "ready")
        self.assertEqual(enrollment.add_sample(9, face(0, 0.2), now=1.2)["samples"], 3)
        self.assertEqual(self.store.list_profiles(), [])
        self.assertEqual(enrollment.finish(now=1.2)["state"], "complete")
        self.assertEqual(self.store.list_profiles()[0]["sample_count"], 3)

    def test_enrollment_cancel_lost_track_and_face_change_save_nothing(self):
        enrollment = EnrollmentManager(self.store)
        enrollment.start("A", 9, 0)
        enrollment.add_sample(9, face(), now=0)
        self.assertEqual(enrollment.cancel()["state"], "cancelled")
        self.assertEqual(self.store.list_profiles(), [])
        enrollment.start("A", 10, 1)
        self.assertEqual(enrollment.on_tracks([11], 1.1)["reason"], "target_lost")
        enrollment.start("A", 10, 2)
        enrollment.add_sample(10, face(), now=2)
        self.assertEqual(enrollment.add_sample(10, face(1), now=2.3)["reason"], "face_changed")
        enrollment.start("A", 10, 3)
        self.assertEqual(enrollment.add_sample(11, face(), now=3)["reason"], "track_changed")
        self.assertEqual(self.store.list_profiles(), [])

    def test_low_quality_and_too_few_samples_do_not_enroll(self):
        enrollment = EnrollmentManager(self.store, timeout_s=2)
        enrollment.start("A", 1, 0)
        self.assertEqual(enrollment.add_sample(1, face(), quality_ok=False, now=0)["samples"], 0)
        enrollment.add_sample(1, face(), now=0.3)
        with self.assertRaises(ValueError):
            enrollment.finish(now=0.5)
        self.assertEqual(enrollment.on_tracks([1], 3)["reason"], "timeout")

    def test_finish_checks_timeout_without_a_camera_update(self):
        enrollment = EnrollmentManager(self.store, timeout_s=2)
        enrollment.start("A", 1, 0)
        for now, vector in zip((0.3, 0.6, 0.9), samples()):
            enrollment.add_sample(1, vector, now=now)
        with self.assertRaises(ValueError):
            enrollment.finish(now=3)
        self.assertFalse(enrollment.status()["active"])
        self.assertEqual(enrollment.status()["reason"], "timeout")
        self.assertEqual(self.store.list_profiles(), [])


class TrackingTests(unittest.TestCase):
    def test_initial_overlapping_people_cannot_be_selected(self):
        tracker = ConservativeTracker()
        tracks = tracker.update([person(0), person(8)], 0)
        self.assertTrue(all(t["association_ambiguous"] for t in tracks))
        for track in tracks:
            with self.assertRaises(ValueError):
                tracker.select(track["track_id"])

    def test_unambiguous_motion_preserves_id_and_extras(self):
        tracker = ConservativeTracker()
        first = tracker.update([person(0)], 0)[0]
        tracker.select(first["track_id"])
        moved = tracker.update([person(4)], 0.1)[0]
        self.assertEqual(first["track_id"], moved["track_id"])
        self.assertEqual(moved["confidence"], 0.9)
        self.assertEqual(tracker.selected_track_id, first["track_id"])

    def test_crossing_ambiguity_retires_ids_and_selected_lock(self):
        tracker = ConservativeTracker()
        first = tracker.update([person(0), person(42)], 0)
        old_ids = {t["track_id"] for t in first}
        tracker.select(first[0]["track_id"])
        crossed = tracker.update([person(17), person(25)], 0.1)
        self.assertTrue(tracker.last_events["ambiguous"])
        self.assertTrue(tracker.last_events["selection_cleared"])
        self.assertIsNone(tracker.selected_track_id)
        self.assertTrue(old_ids.isdisjoint({t["track_id"] for t in crossed}))

    def test_missing_target_pauses_without_ghost_box_then_expires(self):
        tracker = ConservativeTracker(max_missing_s=0.6)
        old = tracker.update([person(0)], 0)[0]["track_id"]
        tracker.select(old)
        self.assertEqual(tracker.update([], 0.1), [])
        self.assertEqual(tracker.selected_track_id, old)
        self.assertEqual(tracker.last_events['selected_hold']['track_id'], old)
        with self.assertRaises(ValueError):
            tracker.select(old)
        new = tracker.update([person(0)], 0.7)[0]["track_id"]
        self.assertNotEqual(new, old)
        self.assertIsNone(tracker.selected_track_id)

    def test_short_miss_reappearance_keeps_original_selected_id(self):
        tracker = ConservativeTracker()
        old = tracker.update([person(0)], 0)[0]['track_id']
        tracker.select(old)
        tracker.update([], .15)
        restored = tracker.update([person(3)], .3)
        self.assertEqual(restored[0]['track_id'], old)
        self.assertEqual(tracker.selected_track_id, old)
        self.assertIsNone(tracker.last_events['selected_hold'])

    def test_weak_detections_can_only_continue_existing_tracks_for_bounded_time(self):
        tracker = ConservativeTracker()
        weak = dict(person(0), confidence=.25)
        self.assertEqual(tracker.update([weak], 0), [])
        old = tracker.update([person(0)], .1)[0]['track_id']
        tracker.select(old)
        continued = tracker.update([weak], .2)
        self.assertEqual(continued[0]['track_id'], old)
        self.assertEqual(continued[0]['observation_strength'], 'weak')
        with self.assertRaises(ValueError):
            tracker.select(old)
        for now in (.4, .6, .8, 1., 1.2):
            self.assertEqual(tracker.update([weak], now)[0]['track_id'], old)
        self.assertEqual(tracker.update([weak], 1.4), [])
        self.assertIsNone(tracker.selected_track_id)

    def test_competing_person_cancels_invisible_hold(self):
        tracker = ConservativeTracker()
        old = tracker.update([person(0)], 0)[0]['track_id']
        tracker.select(old)
        tracker.update([], .1)
        newcomer = tracker.update([person(150)], .2)[0]
        self.assertNotEqual(newcomer['track_id'], old)
        self.assertIsNone(tracker.selected_track_id)
        self.assertIsNone(tracker.last_events['selected_hold'])

    def test_previously_ambiguous_ids_are_never_inherited_after_separation(self):
        tracker = ConservativeTracker()
        ambiguous = tracker.update([person(0), person(8)], 0)
        old = {p['track_id'] for p in ambiguous}
        single = tracker.update([person(0)], .1)[0]
        self.assertFalse(single['association_ambiguous'])
        self.assertNotIn(single['track_id'], old)

    def test_observed_nested_duplicates_no_longer_retire_same_person(self):
        from person_follow.detection_cleanup import consolidate_people
        large = {'bbox':[121,36,518,471], 'depth_m':1.106, 'confidence':.4768}
        small = {'bbox':[134,38,411,260], 'depth_m':1.103, 'confidence':.4714}
        tracker = ConservativeTracker()
        old = tracker.update([large], 0)[0]['track_id']
        tracker.select(old)
        for now, boxes in [(.1,[large,small]),(.2,[small,large]),(.3,[small]),(.4,[large,small])]:
            rows = tracker.update(consolidate_people(boxes, lambda _:1), now)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['track_id'], old)
            self.assertEqual(tracker.selected_track_id, old)

    def test_depth_jump_cannot_inherit_identity_track(self):
        tracker = ConservativeTracker()
        old = tracker.update([person(0, 1)], 0)[0]["track_id"]
        tracker.select(old)
        new = tracker.update([person(0, 3)], 0.1)[0]["track_id"]
        self.assertNotEqual(new, old)
        self.assertIsNone(tracker.selected_track_id)

    def test_reset_or_clock_rewind_never_reuses_ids(self):
        tracker = ConservativeTracker()
        one = tracker.update([person(0)], 10)[0]["track_id"]
        tracker.select(one)
        two = tracker.update([person(0)], 9)[0]["track_id"]
        self.assertGreater(two, one)
        self.assertIsNone(tracker.selected_track_id)
        tracker.reset()
        self.assertGreater(tracker.update([person(0)], 11)[0]["track_id"], two)


if __name__ == "__main__":
    unittest.main()
