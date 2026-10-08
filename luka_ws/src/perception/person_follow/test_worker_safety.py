"""Integration checks for monitor state and commands, with no real vision or I/O.

Run from the repository root:
    python -m unittest person_follow.test_worker_safety -v

Real SQLite enrollment and recognition/tracking cores are exercised. Model,
camera, network, Linux memory probes and background threads are never started.
"""
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import types
import unittest
from unittest import mock

import numpy as np

from person_follow import identity, tracking, target_session, detection_cleanup, appearance


def _embedding(offset=0.0):
    value = np.zeros(128, dtype=np.float32)
    value[0], value[2] = 1.0, offset
    return identity.normalized_embedding(value)


def _load_worker_without_devices():
    root = Path(__file__).resolve().parent
    fake_cv2 = types.ModuleType("cv2")
    fake_vision = types.ModuleType("vision")
    fake_vision.PersonDetector = mock.Mock(side_effect=AssertionError("No real model in state tests"))
    fake_vision.FaceFeatures = mock.Mock(side_effect=AssertionError("No real model in state tests"))
    fake_vision.estimate_person_geometry = mock.Mock(side_effect=AssertionError("No depth processing in state tests"))
    fake_server = types.ModuleType("server")
    fake_server.ROOT, fake_server.DATA, fake_server.BUDGET_GIB = root, root / "data", 7.3
    fake_server.fetch = mock.Mock(side_effect=AssertionError("No network in state tests"))
    fake_server.memory = lambda: {"system_used_gib": 6.0, "budget_gib": 7.3, "swap_mib": 0.0}
    spec = importlib.util.spec_from_file_location("_person_worker_safety_test", root / "worker.py")
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, {"cv2": fake_cv2, "vision": fake_vision, "server": fake_server,
                                       "identity": identity, "tracking": tracking,
                                       "target_session": target_session, "detection_cleanup": detection_cleanup,
                                       "appearance": appearance}):
        spec.loader.exec_module(module)
    return module


worker = _load_worker_without_devices()


class WorkerStateSafetyTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.now = 100.0
        clock = mock.patch.object(worker.time, "monotonic", side_effect=lambda: self.now)
        clock.start()
        self.addCleanup(clock.stop)
        # Never invoke Monitor.__init__, which intentionally starts a worker.
        self.monitor = worker.Monitor.__new__(worker.Monitor)
        monitor = self.monitor
        monitor.lock = threading.RLock()
        monitor.store = identity.IdentityStore(Path(self.directory.name) / "people.sqlite3")
        self.addCleanup(monitor.store.close)
        monitor.recognizer = identity.IdentityRecognizer(monitor.store)
        monitor.enrollment = identity.EnrollmentManager(monitor.store)
        monitor.tracker = tracking.ConservativeTracker()
        monitor.target_session = target_session.TargetSession()
        monitor.tracks = monitor.tracker.update([
            {"bbox": [10, 10, 80, 180], "depth_m": 1.7}], self.now - 0.1)
        self.track_id = monitor.tracks[0]["track_id"]
        monitor.faces = {self.track_id: (self.now - 0.1, {"accepted": True, "embedding": _embedding(),
                                                       "face_bbox": [25, 15, 65, 60], "quality": 0.95})}
        monitor.jpeg = b"fake-jpeg-not-decoded"
        monitor.frame_at, monitor.frame_mono = 1_700_000_000.0, self.now - 0.1
        monitor.error, monitor.loading, monitor.fps = None, False, 5.0
        monitor.inference_s, monitor.enrollment_start, monitor.models = 0.1, None, None
        monitor.generation, monitor.peak_memory = 0, 6.1

    def _known_profile(self):
        monitor = self.monitor
        profile = monitor.store.add_profile("Known person", [_embedding(x) for x in (-0.08, 0, 0.08)])
        for stamp in (self.now - 0.4, self.now - 0.3, self.now - 0.2):
            result = monitor.recognizer.observe(self.track_id, _embedding(), stamp)
        self.assertTrue(result["known"])
        monitor.tracks[0]["identity"] = {"state": "matched", "id": profile["id"], "name": profile["name"]}
        monitor.faces[self.track_id][1]["_identity"] = dict(monitor.tracks[0]["identity"])
        return profile

    def _ready_enrollment(self, elapsed_s=2):
        monitor = self.monitor
        monitor.tracker.select(self.track_id)
        monitor.enrollment.start("New person", self.track_id, now=self.now - elapsed_s)
        monitor.enrollment_start = self.now - elapsed_s
        for stamp, offset in zip((self.now - 1.1, self.now - 0.8, self.now - 0.5), (-0.08, 0, 0.08)):
            monitor.enrollment.add_sample(self.track_id, _embedding(offset), now=stamp)
        self.assertEqual(monitor.enrollment.status()["state"], "ready")

    def test_expired_status_clears_real_tracking_identity_and_pending_enrollment(self):
        profile = self._known_profile()
        self._ready_enrollment()
        self.now += 0.8
        result = self.monitor.status()
        self.assertEqual(result["tracks"], [])
        self.assertIsNone(result["selected_track_id"])
        self.assertIsNone(result["frame_jpeg_base64"])
        self.assertFalse(result["enrollment"]["active"])
        self.assertEqual(result["enrollment"]["reason"], "camera_stale")
        self.assertEqual(self.monitor.tracks, [])
        self.assertEqual(self.monitor.faces, {})
        self.assertEqual(self.monitor.recognizer._states, {})
        with self.assertRaises(ValueError):
            self.monitor.tracker.select(self.track_id)
        self.assertGreater(self.monitor.generation, 0)
        # Saved people survive a camera outage; the pending enrollment does not.
        self.assertEqual([p["id"] for p in self.monitor.store.list_profiles()], [profile["id"]])

    def test_live_person_context_requires_fresh_confirmed_face_and_valid_link(self):
        profile = self._known_profile()
        linked = dict(profile, person_id='voice-existing', voice_link={
            'state': 'linked', 'profile_id': 'voice-existing', 'name': 'Speaker label'})
        with mock.patch.object(self.monitor.store, 'list_profiles', return_value=[linked]):
            public = self.monitor.status()['tracks'][0]['identity']
            self.assertEqual(public['person_id'], 'voice-existing')
            self.assertEqual(public['voice_profile_id'], 'voice-existing')
            self.assertEqual(public['id'], profile['id'])
            self.assertNotIn('person_id', self.monitor.tracks[0]['identity'])
            self.monitor.tracks[0]['identity'] = dict(public, state='no_face')
            self.assertNotIn('person_id', self.monitor.status()['tracks'][0]['identity'])
            self.monitor.tracks[0]['identity'] = public
            self.now += 1
            self.assertEqual(self.monitor.status()['tracks'], [])

    def test_invalid_or_deleted_voice_link_never_preserves_cached_person_context(self):
        profile = self._known_profile()
        self.monitor.tracks[0]['identity'].update(person_id='old', voice_profile_id='old', voice_name='Old name')
        for link in ({}, {'voice_link': {'state': 'missing'}},
                     {'voice_link': {'state': 'unavailable'}},
                     {'person_id': 'mismatch', 'voice_link': {'state': 'linked', 'profile_id': 'other'}}):
            with self.subTest(link=link), mock.patch.object(
                    self.monitor.store, 'list_profiles', return_value=[dict(profile, **link)]):
                public = self.monitor.status()['tracks'][0]['identity']
                self.assertNotIn('person_id', public)
                self.assertNotIn('voice_profile_id', public)
                self.assertNotIn('voice_name', public)

    def test_finish_on_expired_camera_does_not_persist_samples(self):
        self._ready_enrollment()
        self.now += 0.8
        with self.assertRaises(ValueError):
            self.monitor.command("finish-enrollment", {})
        self.assertFalse(self.monitor.enrollment.status()["active"])
        self.assertEqual(self.monitor.store.list_profiles(), [])

    def test_finish_rejects_missing_or_old_face_even_with_current_camera(self):
        self._ready_enrollment()
        for stamp, face in ((self.now - 0.1, {"accepted": False, "reason": "no_face"}),
                            (self.now - 1.0, {"accepted": True, "embedding": _embedding()})):
            with self.subTest(face=face.get("reason", "stale_face")):
                self.monitor.faces[self.track_id] = (stamp, face)
                with self.assertRaises(ValueError):
                    self.monitor.command("finish-enrollment", {})
                self.assertEqual(self.monitor.store.list_profiles(), [])
                self.assertTrue(self.monitor.enrollment.status()["active"])

    def test_finish_requires_same_selected_target(self):
        self._ready_enrollment()
        self.monitor.tracker.clear_selection()
        with self.assertRaises(ValueError):
            self.monitor.command("finish-enrollment", {})
        self.assertEqual(self.monitor.store.list_profiles(), [])

    def test_finish_persists_only_when_visible_selected_face_is_fresh(self):
        self._ready_enrollment()
        reply = self.monitor.command("finish-enrollment", {})
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["enrollment"]["state"], "complete")
        self.assertEqual(self.monitor.store.list_profiles()[0]["sample_count"], 3)

    def test_auto_finish_saves_three_samples_after_wait_with_new_clear_face(self):
        self._ready_enrollment(elapsed_s=16)
        examined = {self.track_id: (self.now - 0.1, {"accepted": True})}
        self.monitor.maybe_finish_enrollment(examined, self.monitor.tracks, self.monitor.frame_mono)
        self.assertEqual(self.monitor.enrollment.status()["state"], "complete")
        self.assertEqual(self.monitor.store.list_profiles()[0]["sample_count"], 3)

    def test_auto_finish_saves_all_eight_samples_without_fifteen_second_wait(self):
        monitor = self.monitor
        monitor.tracker.select(self.track_id)
        monitor.enrollment.start("New person", self.track_id, now=self.now - 5)
        monitor.enrollment_start = self.now - 5
        for index, offset in enumerate((-0.21, -0.15, -0.09, -0.03, 0.03, 0.09, 0.15, 0.21)):
            monitor.enrollment.add_sample(self.track_id, _embedding(offset), now=self.now - 2.8 + 0.3 * index)
        self.assertEqual(monitor.enrollment.status()["samples"], 8)
        examined = {self.track_id: (self.now - 0.1, {"accepted": True})}
        monitor.maybe_finish_enrollment(examined, monitor.tracks, monitor.frame_mono)
        self.assertEqual(monitor.store.list_profiles()[0]["sample_count"], 8)

    def test_auto_finish_does_not_use_cached_face_when_target_turns_away(self):
        self._ready_enrollment(elapsed_s=16)
        # self.faces still contains a fresh accepted cached result. Only a new
        # accepted face in examined may authorize automatic completion.
        for examined in ({}, {self.track_id: (self.now - 0.1, {"accepted": False, "reason": "no_face"})}):
            with self.subTest(new_detection=bool(examined)):
                self.monitor.maybe_finish_enrollment(examined, self.monitor.tracks, self.monitor.frame_mono)
                self.assertTrue(self.monitor.enrollment.status()["active"])
                self.assertEqual(self.monitor.store.list_profiles(), [])

    def test_auto_finish_rejects_stale_or_future_frame_and_face(self):
        self._ready_enrollment(elapsed_s=16)
        for frame_stamp, face_stamp in ((self.now - 1, self.now - 0.1),
                                        (self.now - 0.1, self.now - 1),
                                        (self.now + 1, self.now - 0.1),
                                        (self.now - 0.1, self.now + 1)):
            with self.subTest(frame=frame_stamp, face=face_stamp):
                examined = {self.track_id: (face_stamp, {"accepted": True})}
                self.monitor.maybe_finish_enrollment(examined, self.monitor.tracks, frame_stamp)
                self.assertEqual(self.monitor.store.list_profiles(), [])
                self.assertTrue(self.monitor.enrollment.status()["active"])

    def test_auto_finish_requires_unambiguous_selected_body_in_current_frame(self):
        self._ready_enrollment(elapsed_s=16)
        examined = {self.track_id: (self.now - 0.1, {"accepted": True})}
        self.monitor.maybe_finish_enrollment(examined, [], self.monitor.frame_mono)
        self.assertEqual(self.monitor.store.list_profiles(), [])
        self.monitor.tracks[0]["association_ambiguous"] = True
        self.monitor.maybe_finish_enrollment(examined, self.monitor.tracks, self.monitor.frame_mono)
        self.assertEqual(self.monitor.store.list_profiles(), [])
        self.monitor.tracks[0]["association_ambiguous"] = False
        self.monitor.tracker.clear_selection()
        self.monitor.maybe_finish_enrollment(examined, self.monitor.tracks, self.monitor.frame_mono)
        self.assertEqual(self.monitor.store.list_profiles(), [])

    def test_auto_finish_with_only_three_samples_waits_before_saving(self):
        self._ready_enrollment(elapsed_s=2)
        examined = {self.track_id: (self.now - 0.1, {"accepted": True})}
        self.monitor.maybe_finish_enrollment(examined, self.monitor.tracks, self.monitor.frame_mono)
        self.assertTrue(self.monitor.enrollment.status()["active"])
        self.assertEqual(self.monitor.store.list_profiles(), [])

    def test_enroll_requires_selection_and_clear_face(self):
        data = {"name": "New person", "track_id": self.track_id}
        with self.assertRaises(ValueError):
            self.monitor.command("enroll", data)
        self.assertFalse(self.monitor.enrollment.status()["active"])
        self.monitor.command("select", {"track_id": self.track_id})
        self.monitor.faces[self.track_id][1]["accepted"] = False
        with self.assertRaises(ValueError):
            self.monitor.command("enroll", data)
        self.assertFalse(self.monitor.enrollment.status()["active"])
        self.assertEqual(self.monitor.store.list_profiles(), [])

    def test_selecting_overlapping_person_cannot_start_enrollment(self):
        self.monitor.tracks[0]["association_ambiguous"] = True
        with self.assertRaises(ValueError):
            self.monitor.command("select", {"track_id": self.track_id})
        with self.assertRaises(ValueError):
            self.monitor.command("enroll", {"name": "New person", "track_id": self.track_id})
        self.assertIsNone(self.monitor.tracker.selected_track_id)
        self.assertEqual(self.monitor.store.list_profiles(), [])

    def test_deleting_profile_clears_cached_names_and_recognition_evidence(self):
        profile = self._known_profile()
        self.monitor.command("delete-profile", {"id": profile["id"]})
        self.assertEqual(self.monitor.store.list_profiles(), [])
        self.assertEqual(self.monitor.faces, {})
        self.assertEqual(self.monitor.recognizer._states, {})
        self.assertEqual(self.monitor.tracks[0]["identity"]["state"], "unknown")
        self.assertIsNone(self.monitor.tracks[0]["identity"]["id"])
        self.assertIsNone(self.monitor.tracks[0]["identity"]["name"])
        self.assertFalse(self.monitor.store.match(_embedding())["known"])

    def test_unlock_cancels_unsaved_enrollment_but_preserves_existing_profiles(self):
        profile = self._known_profile()
        self._ready_enrollment()
        self.monitor.command("unlock", {})
        self.assertIsNone(self.monitor.tracker.selected_track_id)
        self.assertFalse(self.monitor.enrollment.status()["active"])
        self.assertEqual(self.monitor.enrollment.status()["reason"], "unlocked")
        self.assertEqual([p["id"] for p in self.monitor.store.list_profiles()], [profile["id"]])

    def test_fresh_status_is_monitor_only_and_does_not_save_pending_samples(self):
        self._ready_enrollment()
        result = self.monitor.status()
        self.assertFalse(result["motion_enabled"])
        self.assertEqual(result["mode"], "monitor")
        self.assertEqual(result["selected_track_id"], self.track_id)
        self.assertTrue(result["tracks"][0]["selected"])
        self.assertTrue(result["enrollment"]["active"])
        self.assertEqual(self.monitor.store.list_profiles(), [])

    def test_http_motion_request_is_rejected_without_loading_models(self):
        body = json.dumps({"track_id": self.track_id}).encode()
        handler = worker.Handler.__new__(worker.Handler)
        handler.monitor = self.monitor
        handler.headers = {"Content-Length": str(len(body))}
        handler.path = "/api/people/follow"
        handler.rfile = io.BytesIO(body)
        handler.reply = mock.Mock()
        handler.do_POST()
        reply, code = handler.reply.call_args.args
        self.assertEqual(code, 400)
        self.assertIn("不支持运动控制", reply["error"])
        self.assertIsNone(self.monitor.models)
        self.assertIsNone(self.monitor.tracker.selected_track_id)
        self.assertEqual(self.monitor.store.list_profiles(), [])

    def test_waiting_target_has_no_public_body_distance_or_current_face(self):
        profile = self._known_profile()
        m = self.monitor
        m.command('select', {'track_id': self.track_id})
        self.now += .15
        m.process_observations([], None, b'new-frame', m.frame_at+.15, self.now, mock.Mock())
        state = m.status()
        self.assertEqual(state['tracks'], [])
        self.assertEqual(state['target_session']['state'], 'waiting_detection')
        self.assertEqual(state['target_session']['name'], profile['name'])
        self.assertFalse(state['target_session']['visible'])
        self.assertFalse(state['target_session']['current_face_verified'])
        with self.assertRaises(ValueError):
            m.command('confirm-target', {'track_id':self.track_id, 'profile_id':profile['id']})
        self.now += .5
        m.frame_mono = self.now
        self.assertFalse(m.status()['target_session']['active'])

    def test_weak_body_cannot_select_confirm_or_enroll(self):
        profile = self._known_profile()
        m = self.monitor
        m.command('select', {'track_id':self.track_id})
        m.tracks[0]['observation_strength'] = 'weak'
        for action,data in [('select',{}), ('confirm-target',{'profile_id':profile['id']}), ('enroll',{'name':'Draft'})]:
            with self.subTest(action=action), self.assertRaises(ValueError):
                m.command(action, dict(data, track_id=self.track_id))
        self.assertEqual(m.store.list_profiles()[0]['sample_count'],3)

    def test_finishing_enrollment_rejects_weak_body_even_with_cached_face(self):
        self._ready_enrollment()
        self.monitor.tracks[0]['observation_strength'] = 'weak'
        with self.assertRaises(ValueError):
            self.monitor.command('finish-enrollment', {})
        self.assertEqual(self.monitor.store.list_profiles(), [])

    def test_manual_target_confirmation_works_without_face_and_does_not_enroll(self):
        profile = self._known_profile()
        self.monitor.tracks[0]['identity'] = {'state': 'no_face', 'id': None, 'name': None}
        self.monitor.faces = {}
        self.monitor.command('select', {'track_id': self.track_id})
        reply = self.monitor.command('confirm-target', {'track_id': self.track_id, 'profile_id': profile['id']})
        self.assertTrue(reply['ok'])
        result = self.monitor.status()
        self.assertEqual(result['target_session']['name'], profile['name'])
        self.assertEqual(result['target_session']['confirmation_source'], 'user_selection')
        self.assertFalse(result['target_session']['current_face_verified'])
        self.assertEqual(result['tracks'][0]['identity']['state'], 'no_face')
        self.assertNotIn('person_id', result['tracks'][0]['identity'])
        self.assertFalse(result['motion_enabled'])
        self.assertEqual(self.monitor.store.list_profiles()[0]['sample_count'], 3)

    def test_confirmed_face_target_survives_turning_away_only_on_continuous_body(self):
        profile = self._known_profile()
        self.monitor.command('select', {'track_id': self.track_id})
        self.assertTrue(self.monitor.status()['target_session']['current_face_verified'])
        self.monitor.tracks[0]['identity'] = {'state': 'no_face', 'id': None, 'name': None}
        target = self.monitor.status()['target_session']
        self.assertEqual(target['name'], profile['name'])
        self.assertEqual(target['identity_basis'], 'face_then_body')
        self.assertFalse(target['current_face_verified'])
        self.monitor.tracks = []
        self.assertFalse(self.monitor.status()['target_session']['active'])
        self.assertIsNone(self.monitor.status()['target_session']['name'])

    def test_manual_confirmation_rejects_unselected_conflicting_deleted_and_stale(self):
        profile = self._known_profile()
        data = {'track_id': self.track_id, 'profile_id': profile['id']}
        with self.assertRaises(ValueError):
            self.monitor.command('confirm-target', data)
        self.monitor.command('select', {'track_id': self.track_id})
        other = self.monitor.store.add_profile('Other', [_embedding(x) for x in (.6, .7, .8)])
        with self.assertRaises(ValueError):
            self.monitor.command('confirm-target', dict(data, profile_id=other['id']))
        with self.assertRaises(ValueError):
            self.monitor.command('confirm-target', dict(data, profile_id='deleted'))
        self.now += 1
        with self.assertRaises(ValueError):
            self.monitor.command('confirm-target', data)
        self.assertFalse(self.monitor.target_session.status()['active'])

    def test_confirm_target_checks_age_again_after_profile_io(self):
        profile = self._known_profile()
        self.monitor.command('select', {'track_id': self.track_id})
        def delayed_profiles():
            self.now += .8
            return [profile]
        with mock.patch.object(self.monitor.store, 'list_profiles', side_effect=delayed_profiles):
            with self.assertRaises(ValueError):
                self.monitor.command('confirm-target', {'track_id': self.track_id, 'profile_id': profile['id']})
        self.assertFalse(self.monitor.target_session.status()['active'])

    def test_select_checks_age_again_after_profile_io(self):
        def delayed_profiles():
            self.now += .8
            return []
        with mock.patch.object(self.monitor.store, 'list_profiles', side_effect=delayed_profiles):
            with self.assertRaises(ValueError):
                self.monitor.command('select', {'track_id': self.track_id})
        self.assertIsNone(self.monitor.tracker.selected_track_id)
        self.assertFalse(self.monitor.target_session.status()['active'])

    def test_manual_confirmation_rejects_ambiguous_and_enrolling_targets(self):
        profile = self._known_profile()
        self.monitor.command('select', {'track_id': self.track_id})
        data = {'track_id': self.track_id, 'profile_id': profile['id']}
        self.monitor.tracks[0]['association_ambiguous'] = True
        with self.assertRaises(ValueError):
            self.monitor.command('confirm-target', data)
        self.monitor.tracks[0]['association_ambiguous'] = False
        self._ready_enrollment()
        with self.assertRaises(ValueError):
            self.monitor.command('confirm-target', data)

    def test_deleting_target_profile_and_unlock_revoke_target_metadata(self):
        profile = self._known_profile()
        self.monitor.command('select', {'track_id': self.track_id})
        self.assertTrue(self.monitor.status()['target_session']['active'])
        self.monitor.command('delete-profile', {'id': profile['id']})
        self.assertFalse(self.monitor.target_session.status()['active'])
        self.assertIsNone(self.monitor.target_session.status()['name'])
        self.monitor.command('unlock', {})
        self.assertIsNone(self.monitor.status()['selected_track_id'])
        self.assertFalse(self.monitor.status()['target_session']['active'])


class StoppedSupervisorProfileTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(__file__).resolve().parent
        spec = importlib.util.spec_from_file_location("_person_supervisor_safety_test", root / "server.py")
        self.server = importlib.util.module_from_spec(spec)
        # Redirect module-owned DATA creation to the temporary directory while
        # executing the real server.py implementation, not a duplicate stub.
        self.server.__file__ = str(Path(self.directory.name) / "server.py")
        spec.loader.exec_module(self.server)
        aliases = mock.patch.dict(sys.modules, {"identity": identity})
        aliases.start()
        self.addCleanup(aliases.stop)
        network = mock.patch.object(self.server, "fetch", side_effect=AssertionError("No network for stopped profile deletion"))
        self.fetch = network.start()
        self.addCleanup(network.stop)
        process = mock.patch.object(self.server.subprocess, "Popen", side_effect=AssertionError("Deletion must not start a model worker"))
        self.popen = process.start()
        self.addCleanup(process.stop)
        self.supervisor = self.server.Supervisor()
        store = identity.IdentityStore(self.server.DATA / "people.sqlite3")
        try:
            self.profile = store.add_profile("Saved person", [_embedding(x) for x in (-0.08, 0, 0.08)])
        finally:
            store.close()

    def _profiles(self):
        store = identity.IdentityStore(self.server.DATA / "people.sqlite3")
        try:
            return store.list_profiles()
        finally:
            store.close()

    def test_stopped_worker_profile_deletion_uses_database_without_starting_models(self):
        self.assertFalse(self.supervisor.alive())
        self.assertEqual(self.supervisor.delete_profile({"id": self.profile["id"]}), {"ok": True})
        self.assertEqual(self._profiles(), [])
        self.assertIsNone(self.supervisor.process)
        self.fetch.assert_not_called()
        self.popen.assert_not_called()

    def test_missing_profile_rejected_while_stopped_without_touching_saved_person(self):
        with self.assertRaises(ValueError):
            self.supervisor.delete_profile({"id": "does-not-exist"})
        self.assertEqual([p["id"] for p in self._profiles()], [self.profile["id"]])
        self.fetch.assert_not_called()
        self.popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
