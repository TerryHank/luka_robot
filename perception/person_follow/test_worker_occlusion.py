"""Real worker/tracker/session occlusion checks with only temporary local data.

No model, camera, network, worker thread or robot command is started. Synthetic
512-D appearance vectors exercise the same tracker entry point used by frames;
face templates live in a temporary SQLite database owned by each test.
"""
import json
from pathlib import Path
import unittest
from unittest import mock

import numpy as np

from person_follow import tracking
from person_follow import test_worker_safety as fixtures


def appearance(axis=0):
    vector = np.zeros(512, dtype=np.float32)
    vector[axis] = 1.
    return vector


def detection(x=10):
    return dict(bbox=[x, 10, x+70, 180], confidence=.8, depth_m=1.7)


class WorkerOcclusionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.WorkerStateSafetyTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.monitor = self.fixture.monitor
        self.monitor.tracker = tracking.ConservativeTracker(occlusion_reid=True)
        self.monitor.tracks = []
        self.monitor.faces = {}
        self.monitor.recognizer.prune([])
        self.path = Path(self.fixture.directory.name) / 'tracking_event.json'
        self.monitor.tracking_recorder = fixtures.worker.TrackingEventRecorder(self.path)
        for now in (100., 100.1, 100.2):
            public = self.frame(now, [detection()], {0: appearance()})
        self.track_id = public['tracks'][0]['track_id']
        self.fixture.track_id = self.track_id
        self.profile = self.monitor.store.add_profile('Temporary owner label', [
            fixtures._embedding(offset) for offset in (-.08, 0, .08)])
        self.monitor.command('select', {'track_id': self.track_id})
        self.monitor.command('confirm-target', {'track_id': self.track_id,
                                               'profile_id': self.profile['id']})
        self.assertGreaterEqual(len(self.monitor.tracker._appearance_templates[self.track_id]), 2)

    def frame(self, now, detections=(), embeddings=None, face=False):
        self.fixture.now = now
        faces = mock.Mock()
        faces.face_features.return_value = ({
            'accepted': True, 'embedding': fixtures._embedding(),
            'face_bbox': [25, 15, 65, 60], 'quality': .95}
            if face else {'accepted': False, 'reason': 'no_face'})
        accepted = self.monitor.process_observations(
            list(detections), None, b'fixture-jpeg', 1700000000+now, now, faces,
            appearance_embeddings=embeddings)
        self.assertTrue(accepted)
        if not detections:
            faces.face_features.assert_not_called()
        return self.monitor.status()

    def hide_until(self, now):
        # Keep camera frames fresh throughout the absence. Target age may
        # exceed .7s; this must never be confused with camera-frame staleness.
        result = None
        while self.fixture.now < now:
            result = self.frame(min(now, round(self.fixture.now+.4, 6)))
        return result

    def assert_waiting(self, public):
        target = public['target_session']
        self.assertEqual(public['tracks'], [])
        self.assertEqual(public['selected_track_id'], self.track_id)
        self.assertTrue(target['active'])
        self.assertEqual(target['state'], 'waiting_occlusion')
        self.assertFalse(target['visible'])
        self.assertFalse(target['current_face_verified'])
        self.assertFalse(target['confirmation_available'])
        self.assertFalse(target['motion_enabled'])
        self.assertFalse(target['motion_ready'])
        self.assertEqual(target['profile_id'], self.profile['id'])
        self.assertEqual(target['confirmation_source'], 'user_selection')
        self.assertFalse(target['face_verified'])
        for key in ('bbox', 'depth_m', 'face_bbox', 'person_id', 'voice_profile_id'):
            self.assertNotIn(key, target)

    def assert_unlocked(self, public):
        self.assertIsNone(public['selected_track_id'])
        self.assertFalse(public['target_session']['active'])
        self.assertIsNone(public['target_session']['profile_id'])
        self.assertIsNone(public['target_session']['name'])
        self.assertTrue(all(row['track_id'] != self.track_id for row in public['tracks']))

    def test_two_second_occlusion_requires_two_appearance_frames_then_keeps_same_id(self):
        public = self.hide_until(102.2)
        self.assert_waiting(public)
        self.assertAlmostEqual(public['target_session']['missing_age_s'], 2.)
        self.assertAlmostEqual(public['target_session']['hold_remaining_s'], 1.)
        pending = self.frame(102.3, [detection(14)], {0: appearance()})
        self.assert_waiting(pending)
        self.assertEqual(self.monitor.faces, {})
        recovered = self.frame(102.4, [detection(15)], {0: appearance()})
        row, target = recovered['tracks'][0], recovered['target_session']
        self.assertEqual(row['track_id'], self.track_id)
        self.assertTrue(row['recovery_proof']['verified'])
        self.assertAlmostEqual(row['recovery_proof']['episode_last_seen'], 100.2)
        self.assertEqual(row['identity']['state'], 'no_face')
        self.assertTrue(target['active'])
        self.assertTrue(target['visible'])
        self.assertEqual(target['profile_id'], self.profile['id'])
        self.assertEqual(target['name'], self.profile['name'])
        self.assertEqual(target['confirmation_source'], 'user_selection')
        self.assertFalse(target['current_face_verified'])
        self.assertFalse(target['face_verified'])
        self.assertFalse(target['motion_ready'])
        self.assertFalse(target['motion_enabled'])
        continued = self.frame(102.5, [detection(16)], {0: appearance()})
        self.assertEqual(continued['tracks'][0]['track_id'], self.track_id)
        self.assertEqual(continued['target_session']['profile_id'], self.profile['id'])

    def test_absence_clears_cached_face_and_cancels_ready_enrollment_without_saving(self):
        monitor = self.monitor
        for stamp in (99.7, 99.8, 99.9):
            monitor.recognizer.observe(self.track_id, fixtures._embedding(), stamp)
        monitor.faces[self.track_id] = (100.2, dict(accepted=True,
            embedding=fixtures._embedding(), face_bbox=[25, 15, 65, 60], quality=.95))
        self.fixture._ready_enrollment(elapsed_s=16)
        self.assertEqual(monitor.enrollment.status()['state'], 'ready')
        public = self.hide_until(102.2)
        self.assert_waiting(public)
        self.assertEqual(monitor.faces, {})
        self.assertEqual(monitor.recognizer._states, {})
        self.assertFalse(public['enrollment']['active'])
        self.assertEqual(public['enrollment']['reason'], 'target_lost')
        self.assertEqual([p['id'] for p in monitor.store.list_profiles()], [self.profile['id']])
        for action, data in (
            ('select', {'track_id': self.track_id}),
            ('confirm-target', {'track_id': self.track_id, 'profile_id': self.profile['id']}),
            ('enroll', {'track_id': self.track_id, 'name': 'Must not be saved'}),
            ('finish-enrollment', {}),
        ):
            with self.subTest(action=action), self.assertRaises(ValueError):
                monitor.command(action, data)
            self.assert_waiting(monitor.status())

    def test_returning_face_restarts_confirmation_instead_of_inheriting_cached_match(self):
        self.hide_until(102.)
        self.frame(102.1, [detection()], {0: appearance()}, face=True)
        public = self.frame(102.2, [detection()], {0: appearance()}, face=True)
        identity = public['tracks'][0]['identity']
        self.assertEqual(identity['state'], 'unknown')
        self.assertEqual(identity['reason'], 'confirming')
        self.assertEqual(self.monitor.recognizer._states[self.track_id]['count'], 1)
        self.assertFalse(public['target_session']['current_face_verified'])
        self.assertEqual(public['target_session']['profile_id'], self.profile['id'])

    def test_stranger_appearance_clears_lock_and_later_original_cannot_reclaim_it(self):
        self.hide_until(102.)
        stranger = self.frame(102.1, [detection()], {0: appearance(1)})
        self.assert_unlocked(stranger)
        self.assertEqual(stranger['tracking_diagnostics']['occlusion_reid_reason'], 'appearance_mismatch')
        self.frame(102.2, [detection()], {0: appearance()})
        self.assert_unlocked(self.frame(102.3, [detection()], {0: appearance()}))

    def test_two_similarly_matching_candidates_clear_lock_without_assigning_old_name(self):
        self.hide_until(102.)
        public = self.frame(102.1, [detection(0), detection(30)],
                            {0: appearance(), 1: appearance()})
        self.assert_unlocked(public)
        self.assertEqual(public['tracking_diagnostics']['occlusion_reid_reason'],
                         'recovery_candidates_ambiguous')
        self.assertTrue(all(row['identity']['state'] != 'matched' for row in public['tracks']))

    def test_camera_staleness_clears_private_templates_and_prevents_recovery(self):
        self.hide_until(102.)
        self.fixture.now += .8
        public = self.monitor.status()
        self.assert_unlocked(public)
        self.assertEqual(self.monitor.tracker._appearance_templates, {})
        self.assertIsNone(self.monitor.tracker._occlusion_episode)
        self.frame(102.9, [detection()], {0: appearance()})
        self.assert_unlocked(self.frame(103., [detection()], {0: appearance()}))

    def test_new_frame_after_unpolled_camera_gap_cannot_resume_old_occlusion_episode(self):
        self.assert_waiting(self.frame(100.3))
        generation = self.monitor.generation
        # No status call, invalidation callback or frame is processed during
        # this 1.1s gap. The newly arrived image is itself fresh, but cannot
        # retroactively preserve continuity with the old camera observation.
        first = self.frame(101.4, [detection()], {0: appearance()})
        self.assert_unlocked(first)
        self.assertGreater(self.monitor.generation, generation)
        self.assertNotIn(self.track_id, self.monitor.tracker._appearance_templates)
        self.assertIsNone(self.monitor.tracker._occlusion_episode)
        second = self.frame(101.5, [detection()], {0: appearance()})
        self.assert_unlocked(second)
        events = list(self.monitor.tracking_recorder.frames)
        self.assertTrue(any(row['outcome'] == 'invalidated' and
                            row['invalidation_reason'] == 'camera_stale' for row in events))

    def test_explicit_unlock_prevents_same_appearance_from_recovering_selection(self):
        self.hide_until(102.)
        self.monitor.command('unlock', {})
        self.assert_unlocked(self.monitor.status())
        self.assertNotIn(self.track_id, self.monitor.tracker._appearance_templates)
        self.frame(102.1, [detection()], {0: appearance()})
        self.assert_unlocked(self.frame(102.2, [detection()], {0: appearance()}))

    def test_fixed_occlusion_deadline_cannot_be_extended_by_frames_or_status_polls(self):
        public = self.hide_until(103.1)
        self.assert_waiting(public)
        self.assertAlmostEqual(public['target_session']['hold_remaining_s'], .1)
        expired = self.frame(103.21)
        self.assert_unlocked(expired)
        self.frame(103.3, [detection()], {0: appearance()})
        self.assert_unlocked(self.frame(103.4, [detection()], {0: appearance()}))

    def test_deleted_profile_cannot_return_as_historical_identity_after_body_recovery(self):
        self.hide_until(102.)
        self.monitor.command('delete-profile', {'id': self.profile['id']})
        deleted = self.monitor.status()
        self.assertFalse(deleted['target_session']['active'])
        self.assertEqual(deleted['profiles'], [])
        self.frame(102.1, [detection()], {0: appearance()})
        recovered = self.frame(102.2, [detection()], {0: appearance()})
        # The tracker can keep its geometric number, but deleting a profile
        # irrevocably ends its named target session until explicit reselection.
        self.assertFalse(recovered['target_session']['active'])
        self.assertIsNone(recovered['target_session']['profile_id'])
        self.assertIsNone(recovered['target_session']['name'])
        self.assertEqual(recovered['profiles'], [])
        self.assertTrue(all(row['identity']['state'] != 'matched' for row in recovered['tracks']))

    def test_public_status_and_diagnostics_serialize_without_appearance_or_face_vectors(self):
        def assert_no_vectors(value):
            self.assertNotIsInstance(value, np.ndarray)
            if isinstance(value, dict):
                for key, item in value.items():
                    self.assertNotIn(key, ('embedding', 'embeddings', 'appearance_embeddings',
                                          'appearance_templates', '_appearance_templates'))
                    assert_no_vectors(item)
            elif isinstance(value, (tuple, list)):
                self.assertLess(len(value), 512)
                for item in value:
                    assert_no_vectors(item)

        waiting = self.hide_until(102.)
        self.frame(102.1, [detection()], {0: appearance()})
        recovered = self.frame(102.2, [detection()], {0: appearance()})
        for state in (waiting, recovered):
            assert_no_vectors(state)
            self.assertLess(len(json.dumps(state, allow_nan=False)), 20_000)
        # Trigger an actual critical diagnostic write in the temporary folder.
        self.fixture.now = 103.1
        self.monitor.status()
        paths = (self.path, self.path.with_name('tracking_selected_loss.json'))
        for path in paths:
            self.assertTrue(path.exists())
            raw = path.read_text(encoding='utf-8')
            self.assertLess(len(raw), 200_000)
            self.assertNotIn(self.profile['id'], raw)
            self.assertNotIn(self.profile['name'], raw)
            payload = json.loads(raw)
            assert_no_vectors(payload)
            self.assertLessEqual(len(payload['frames']), 160)
        assert_no_vectors(list(self.monitor.tracking_recorder.frames))


if __name__ == '__main__':
    unittest.main()
