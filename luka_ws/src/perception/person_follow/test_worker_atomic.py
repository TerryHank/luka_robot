"""Frame-commit concurrency and weak-body regressions; no devices or models."""
import base64
import threading
import unittest
from unittest import mock

from person_follow import test_worker_safety as fixtures


class WorkerAtomicFrameTests(unittest.TestCase):
    def setUp(self):
        # Reuse the real monitor/store/tracker fixture without starting the
        # Monitor constructor, camera, model, network, or Linux probes.
        self.fixture = fixtures.WorkerStateSafetyTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.monitor = self.fixture.monitor
        self.track_id = self.fixture.track_id

    @staticmethod
    def detection(confidence=.9):
        return dict(bbox=[10, 10, 80, 180], depth_m=1.7, confidence=confidence)

    def test_status_cannot_see_old_empty_tracks_during_held_target_return(self):
        fixture, monitor = self.fixture, self.monitor
        profile = fixture._known_profile()
        monitor.command('select', {'track_id': self.track_id})
        unused_faces = mock.Mock()
        unused_faces.face_features.side_effect = AssertionError('No face without a body')
        fixture.now = 100.1
        monitor.process_observations([], None, b'missing-frame', 1700000000.1,
                                     fixture.now, unused_faces)
        held = monitor.status()['target_session']
        self.assertEqual(held['state'], 'waiting_detection')
        self.assertTrue(held['active'])
        self.assertEqual(monitor.tracks, [])
        unused_faces.face_features.assert_not_called()

        entered_face = threading.Event()
        release_face = threading.Event()
        reader_started = threading.Event()
        reader_finished = threading.Event()
        errors, results = [], []

        def blocking_face(image, bbox):
            entered_face.set()
            if not release_face.wait(2):
                raise AssertionError('Test did not release face extraction')
            return {'accepted': False, 'reason': 'no_face'}

        faces = mock.Mock()
        faces.face_features.side_effect = blocking_face
        fixture.now = 100.2

        def write_frame():
            try:
                monitor.process_observations([self.detection()], None, b'returned-frame',
                                             1700000000.2, fixture.now, faces)
            except BaseException as exc:
                errors.append(exc)

        def read_status():
            reader_started.set()
            try:
                results.append(monitor.status())
            except BaseException as exc:
                errors.append(exc)
            finally:
                reader_finished.set()

        writer = threading.Thread(target=write_frame, daemon=True)
        reader = threading.Thread(target=read_status, daemon=True)
        writer.start()
        try:
            self.assertTrue(entered_face.wait(1), 'Returning frame must reach face work')
            # This is precisely the dangerous intermediate state in the old
            # implementation: tracker returned, public frame not committed yet.
            self.assertIsNone(monitor.tracker.last_events['selected_hold'])
            self.assertEqual(monitor.tracks, [])
            reader.start()
            self.assertTrue(reader_started.wait(1))
            self.assertFalse(reader_finished.wait(.08),
                             'Status must wait for the atomic frame commit')
        finally:
            release_face.set()
            writer.join(2)
            if reader.ident is not None:
                reader.join(2)
        self.assertFalse(writer.is_alive())
        self.assertFalse(reader.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 1)
        public = results[0]
        self.assertEqual([row['track_id'] for row in public['tracks']], [self.track_id])
        self.assertEqual(base64.b64decode(public['frame_jpeg_base64']), b'returned-frame')
        self.assertTrue(public['target_session']['active'])
        self.assertTrue(public['target_session']['visible'])
        self.assertEqual(public['target_session']['profile_id'], profile['id'])
        self.assertEqual(public['target_session']['identity_basis'], 'face_then_body')
        self.assertFalse(public['target_session']['current_face_verified'])
        self.assertFalse(public['motion_enabled'])

    def test_weak_continuation_clears_face_cache_and_cannot_finish_enrollment(self):
        fixture, monitor = self.fixture, self.monitor
        profile = fixture._known_profile()
        monitor.command('select', {'track_id': self.track_id})
        fixture._ready_enrollment(elapsed_s=16)
        self.assertEqual(monitor.enrollment.status()['samples'], 3)
        faces = mock.Mock()
        faces.face_features.side_effect = AssertionError('Weak body must not process a face')
        fixture.now = 100.1
        monitor.process_observations([self.detection(.25)], None, b'weak-frame',
                                     1700000000.1, fixture.now, faces)
        public = monitor.status()
        row = public['tracks'][0]
        self.assertEqual(row['track_id'], self.track_id)
        self.assertEqual(row['observation_strength'], 'weak')
        self.assertEqual(row['identity']['state'], 'no_face')
        self.assertEqual(row['identity']['reason'], 'weak_body_detection')
        self.assertIsNone(row['face_bbox'])
        self.assertNotIn(self.track_id, monitor.faces)
        self.assertTrue(public['target_session']['active'])
        self.assertEqual(public['target_session']['profile_id'], profile['id'])
        self.assertFalse(public['target_session']['current_face_verified'])
        self.assertTrue(public['enrollment']['active'])
        self.assertEqual(public['enrollment']['samples'], 3)
        self.assertEqual([p['id'] for p in monitor.store.list_profiles()], [profile['id']])
        with self.assertRaises(ValueError):
            monitor.command('finish-enrollment', {})
        with self.assertRaises(ValueError):
            monitor.command('confirm-target', {'track_id': self.track_id,
                                               'profile_id': profile['id']})
        faces.face_features.assert_not_called()


if __name__ == '__main__':
    unittest.main()
