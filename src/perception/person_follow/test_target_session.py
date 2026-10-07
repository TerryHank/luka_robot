"""Run: python -m unittest person_follow.test_target_session -v."""
import copy
import unittest

from person_follow.target_session import TargetSession


PROFILES = {"face-a": {"id": "face-a", "name": "主人"},
            "face-b": {"id": "face-b", "name": "访客"}}


def body(track_id=1, profile=None, **extra):
    identity = (dict(state="matched", id=profile, name=PROFILES[profile]["name"])
                if profile else dict(state="no_face", id=None, name=None))
    return dict(track_id=track_id, identity=identity, visible=True, **extra)


class TargetSessionTests(unittest.TestCase):
    def setUp(self):
        self.target = TargetSession()

    def update(self, tracks, selected=1, now=1, fresh=True, profiles=PROFILES, hold=None):
        return self.target.update(tracks, selected, now, fresh=fresh,
                                  valid_profiles=profiles, hold=hold)

    def test_explicit_body_selection_does_not_require_close_face(self):
        status = self.update([body()])
        self.assertTrue(status["active"])
        self.assertEqual(status["state"], "body_locked")
        self.assertEqual(status["identity_basis"], "explicit_selection")
        self.assertIsNone(status["name"])
        self.assertFalse(status["motion_enabled"])
        self.assertEqual(status["mode"], "visual_only")

    def test_unselected_known_person_does_not_start_session(self):
        status = self.update([body(profile="face-a")], selected=None)
        self.assertFalse(status["active"])
        self.assertIsNone(status["name"])

    def test_turning_away_preserves_only_separate_body_identity(self):
        known = body(profile="face-a")
        original = copy.deepcopy(known)
        status = self.update([known])
        self.assertEqual(known, original)
        self.assertEqual(status["identity_basis"], "current_face")
        self.assertTrue(status["face_currently_matched"])
        unknown = body()
        status = self.update([unknown], now=1.2)
        self.assertEqual(status["name"], "主人")
        self.assertEqual(status["state"], "body_tracking")
        self.assertEqual(status["identity_basis"], "face_then_body")
        self.assertFalse(status["face_currently_matched"])
        self.assertEqual(unknown["identity"]["state"], "no_face")
        self.assertIsNone(unknown["identity"]["name"])

    def test_face_candidate_cannot_claim_identity(self):
        row = body()
        row["identity"] = dict(state="unknown", id="face-a", name="主人", voice_name="主人")
        status = self.update([row])
        self.assertTrue(status["active"])
        self.assertIsNone(status["profile_id"])
        self.assertIsNone(status["name"])

    def test_unknown_face_on_confirmed_continuous_body_is_not_new_identity(self):
        self.update([body(profile="face-a")])
        row = body()
        row["identity"] = dict(state="unknown", id="face-b", name="访客")
        status = self.update([row], now=1.2)
        self.assertEqual(status["profile_id"], "face-a")
        self.assertFalse(status["face_currently_matched"])

    def test_missing_body_immediately_cancels_and_same_id_does_not_reacquire(self):
        self.update([body(profile="face-a")])
        status = self.update([], now=1.1)
        self.assertFalse(status["active"])
        self.assertEqual(status["reason"], "target_lost")
        self.assertIsNone(status["name"])
        status = self.update([body(profile="face-a")], now=1.2)
        self.assertFalse(status["active"])
        self.assertEqual(status["reason"], "target_lost")

    def test_camera_stale_cancels_until_explicit_reselection(self):
        self.update([body(profile="face-a")])
        status = self.update([body()], now=1.1, fresh=False)
        self.assertEqual(status["reason"], "camera_stale")
        self.assertFalse(self.update([body()], now=1.2)["active"])
        self.target.reset("selected")
        status = self.update([body()], now=1.3)
        self.assertTrue(status["active"])
        self.assertIsNone(status["name"])

    def test_crossing_ambiguity_cancels_instead_of_transferring_name(self):
        self.update([body(profile="face-a")])
        status = self.update([body(association_ambiguous=True), body(2)], now=1.1)
        self.assertFalse(status["active"])
        self.assertEqual(status["reason"], "association_ambiguous")
        self.assertIsNone(status["name"])
        status = self.update([body(profile="face-b"), body(2)], now=1.2)
        self.assertFalse(status["active"])

    def test_conflicting_confirmed_face_latches_inactive(self):
        self.update([body(profile="face-a")])
        status = self.update([body(profile="face-b")], now=1.2)
        self.assertFalse(status["active"])
        self.assertEqual(status["reason"], "identity_conflict")
        self.assertIsNone(status["profile_id"])
        self.assertFalse(self.update([body(profile="face-b")], now=1.3)["active"])

    def test_switch_selected_body_does_not_copy_identity(self):
        self.update([body(profile="face-a"), body(2)])
        status = self.update([body(profile="face-a"), body(2)], selected=2, now=1.2)
        self.assertTrue(status["active"])
        self.assertEqual(status["track_id"], 2)
        self.assertIsNone(status["profile_id"])
        self.assertIsNone(status["name"])

    def test_deleted_profile_cancels_even_when_face_is_absent(self):
        self.update([body(profile="face-a")])
        status = self.update([body()], now=1.2, profiles={})
        self.assertFalse(status["active"])
        self.assertEqual(status["reason"], "profile_deleted")
        self.assertFalse(self.update([body(profile="face-a")], now=1.3)["active"])

    def test_removed_profile_cannot_be_initially_acquired_from_cached_match(self):
        status = self.update([body(profile="face-a")], profiles={})
        self.assertFalse(status["active"])
        self.assertEqual(status["reason"], "profile_deleted")

    def test_duplicate_id_or_invisible_track_cancels(self):
        self.update([body(profile="face-a")])
        status = self.update([body(), body()], now=1.2)
        self.assertFalse(status["active"])
        self.assertEqual(status["reason"], "target_ambiguous")
        self.target.reset("selected")
        row = body()
        row["visible"] = False
        self.assertFalse(self.update([row], now=1.3)["active"])

    def test_unselect_and_explicit_reselect_can_start_new_session(self):
        self.update([body(profile="face-a")])
        self.update([], now=1.1)
        self.update([body()], selected=None, now=1.2)
        status = self.update([body()], now=1.3)
        self.assertTrue(status["active"])
        self.assertIsNone(status["name"])

    def test_profile_catalog_name_is_authoritative(self):
        renamed = copy.deepcopy(PROFILES)
        renamed["face-a"]["name"] = "新称呼"
        status = self.update([body(profile="face-a")], profiles=renamed)
        self.assertEqual(status["name"], "新称呼")
        self.assertEqual(status["profile_id"], "face-a")

    def test_bad_clock_or_catalog_invalidates(self):
        self.update([body(profile="face-a")], now=2)
        status = self.update([body()], now=1)
        self.assertFalse(status["active"])
        self.assertEqual(status["reason"], "clock_reversed")
        self.target.reset("selected")
        status = self.update([body()], now=float("nan"))
        self.assertFalse(status["active"])
        self.assertEqual(status["reason"], "invalid_timestamp")
        self.target.reset("selected")
        status = self.update([body()], profiles=[])
        self.assertFalse(status["active"])
        self.assertEqual(status["reason"], "profile_catalog_unavailable")

    def test_output_is_detached_from_session(self):
        status = self.update([body(profile="face-a")])
        status["name"] = "Changed elsewhere"
        self.assertEqual(self.target.status()["name"], "主人")

    def test_profile_id_alias_for_confirmed_recognizer_result(self):
        row = body(profile="face-a")
        row["identity"]["profile_id"] = row["identity"].pop("id")
        self.assertEqual(self.update([row])["profile_id"], "face-a")

    def test_user_can_confirm_distant_body_without_claiming_face_verification(self):
        row = body()
        self.update([row])
        status = self.target.confirm(1, "face-a", PROFILES, 1.1)
        self.assertTrue(status["active"])
        self.assertEqual(status["confirmation_source"], "user_selection")
        self.assertEqual(status["identity_basis"], "user_selection")
        self.assertEqual(status["name"], "主人")
        self.assertEqual(status["confirmed_name"], "主人")
        self.assertEqual(status["face_profile_id"], "face-a")
        self.assertFalse(status["face_verified"])
        self.assertFalse(status["current_face_verified"])
        self.assertEqual(row["identity"]["state"], "no_face")
        status = self.update([body()], now=1.2)
        self.assertEqual(status["name"], "主人")
        self.assertEqual(status["confirmation_source"], "user_selection")

    def test_manual_target_can_gain_face_confirmation_without_hiding_original_source(self):
        self.update([body()])
        self.target.confirm(1, "face-a", PROFILES, 1.1)
        status = self.update([body(profile="face-a")], now=1.2)
        self.assertTrue(status["face_verified"])
        self.assertTrue(status["current_face_verified"])
        self.assertEqual(status["confirmation_source"], "user_selection")
        status = self.update([body()], now=1.3)
        self.assertTrue(status["face_verified"])
        self.assertFalse(status["current_face_verified"])
        self.assertEqual(status["identity_basis"], "face_then_body")

    def test_manual_confirmation_cannot_override_matched_face(self):
        self.update([body(profile="face-a")])
        with self.assertRaisesRegex(ValueError, "conflicts"):
            self.target.confirm(1, "face-b", PROFILES, 1.1)
        self.assertEqual(self.target.status()["profile_id"], "face-a")
        self.assertTrue(self.target.status()["current_face_verified"])

    def test_contradictory_face_after_manual_confirmation_cancels(self):
        self.update([body()])
        self.target.confirm(1, "face-a", PROFILES, 1.1)
        status = self.update([body(profile="face-b")], now=1.2)
        self.assertFalse(status["active"])
        self.assertEqual(status["reason"], "identity_conflict")
        self.assertIsNone(status["confirmation_source"])

    def test_manual_confirmation_requires_active_exact_target_existing_profile_and_freshness(self):
        with self.assertRaises(ValueError):
            self.target.confirm(1, "face-a", PROFILES, 1)
        self.target.reset("selected")
        self.update([body()])
        with self.assertRaises(ValueError):
            self.target.confirm(2, "face-a", PROFILES, 1.1)
        with self.assertRaises(ValueError):
            self.target.confirm(1, "nonexistent", PROFILES, 1.1)
        with self.assertRaises(ValueError):
            self.target.confirm(1, "face-a", [], 1.1)
        with self.assertRaisesRegex(ValueError, "stale"):
            self.target.confirm(1, "face-a", PROFILES, 2)
        self.assertFalse(self.target.status()["active"])
        self.assertFalse(self.update([body()], now=2.1)["active"])

    def held(self, stamp=1, age=.2, track_id=1, **extra):
        return dict(track_id=track_id, last_seen=stamp, missing_age_s=age,
                    reason="temporary_detection_miss", **extra)

    def test_explicit_short_detection_hold_preserves_identity_without_visible_claim(self):
        self.update([body(profile="face-a")])
        status = self.update([], now=1.2, hold=self.held())
        self.assertTrue(status["active"])
        self.assertEqual(status["state"], "waiting_detection")
        self.assertEqual(status["track_id"], 1)
        self.assertEqual(status["name"], "主人")
        self.assertEqual(status["confirmation_source"], "face_match")
        self.assertFalse(status["current_face_verified"])
        self.assertFalse(status["visible"])
        self.assertFalse(status["motion_ready"])
        self.assertFalse(status["motion_enabled"])
        self.assertFalse(status["confirmation_available"])
        self.assertAlmostEqual(status["missing_age_s"], .2)
        self.assertAlmostEqual(status["hold_remaining_s"], .4)
        self.assertEqual(status["last_seen"], 1)
        self.assertNotIn("bbox", status)
        self.assertNotIn("depth_m", status)

    def test_same_id_revalidated_by_tracker_resumes_without_new_face(self):
        self.update([body()])
        self.target.confirm(1, "face-a", PROFILES, 1.05)
        self.update([], now=1.2, hold=self.held())
        status = self.update([body()], now=1.3)
        self.assertTrue(status["active"])
        self.assertTrue(status["visible"])
        self.assertEqual(status["state"], "body_tracking")
        self.assertEqual(status["name"], "主人")
        self.assertFalse(status["current_face_verified"])
        self.assertIsNone(status["missing_age_s"])
        self.assertIsNone(status["hold_remaining_s"])

    def test_polling_cannot_refresh_hold_timer(self):
        self.update([body(profile="face-a")])
        self.update([], now=1.2, hold=self.held())
        status = self.update([], now=1.5, hold=self.held())
        self.assertEqual(status["last_seen"], 1)
        self.assertAlmostEqual(status["hold_remaining_s"], .1)
        status = self.update([], now=1.61, hold=self.held())
        self.assertFalse(status["active"])
        self.assertEqual(status["reason"], "detection_hold_expired")
        self.assertFalse(self.update([body(profile="face-a")], now=1.7)["active"])

    def test_newer_hold_stamp_cannot_extend_hold_without_visible_observation(self):
        self.update([body(profile="face-a")])
        self.update([], now=1.2, hold=self.held())
        status = self.update([], now=1.4, hold=self.held(stamp=1.3, age=.1))
        self.assertFalse(status["active"])
        self.assertIsNone(status["name"])

    def test_hold_cannot_start_new_or_changed_target(self):
        status = self.update([], now=1.2, hold=self.held())
        self.assertFalse(status["active"])
        self.target.reset("selected")
        self.update([body(profile="face-a")], now=1.3)
        status = self.update([], selected=2, now=1.4,
                             hold=self.held(stamp=1.3, age=.1, track_id=2))
        self.assertFalse(status["active"])
        self.assertIsNone(status["name"])

    def test_other_visible_person_blocks_hold(self):
        self.update([body(profile="face-a")])
        status = self.update([body(2)], now=1.2, hold=self.held())
        self.assertFalse(status["active"])
        self.assertIsNone(status["name"])

    def test_ambiguous_return_and_conflicting_face_cancel_held_target(self):
        for row in (body(association_ambiguous=True), body(profile="face-b")):
            with self.subTest(row=row):
                self.target.reset("selected")
                self.update([body(profile="face-a")])
                self.update([], now=1.2, hold=self.held())
                self.assertFalse(self.update([row], now=1.3)["active"])

    def test_hold_does_not_hide_camera_staleness_or_profile_deletion(self):
        for kwargs in (dict(fresh=False), dict(profiles={})):
            with self.subTest(kwargs=kwargs):
                self.target.reset("selected")
                self.update([body(profile="face-a")])
                status = self.update([], now=1.2, hold=self.held(), **kwargs)
                self.assertFalse(status["active"])
                self.assertIsNone(status["name"])

    def test_manual_confirmation_cannot_use_held_target(self):
        self.update([body()])
        self.update([], now=1.2, hold=self.held())
        with self.assertRaisesRegex(ValueError, "temporarily missing"):
            self.target.confirm(1, "face-a", PROFILES, 1.25)
        self.assertTrue(self.target.status()["active"])
        self.assertIsNone(self.target.status()["profile_id"])

    def test_malformed_or_expired_hold_never_preserves_target(self):
        for bad in (None, {}, self.held(track_id=2), self.held(stamp=1.3),
                    self.held(stamp=1.1, age=.1), self.held(association_ambiguous=True),
                    self.held(stamp=float('nan')), self.held(age=float('inf')),
                    self.held(stamp=.1), self.held(age=.7),
                    dict(self.held(), reason="association_ambiguous")):
            with self.subTest(hold=bad):
                self.target.reset("selected")
                self.update([body(profile="face-a")])
                status = self.update([], now=1.2, hold=bad)
                self.assertFalse(status["active"])
                self.assertIsNone(status["name"])

    def test_late_same_id_return_after_hold_expiry_cannot_resume(self):
        self.update([body(profile="face-a")])
        self.update([], now=1.2, hold=self.held())
        status = self.update([body(profile="face-a")], now=1.7)
        self.assertFalse(status["active"])
        self.assertEqual(status["reason"], "detection_hold_expired")


if __name__ == "__main__":
    unittest.main()
