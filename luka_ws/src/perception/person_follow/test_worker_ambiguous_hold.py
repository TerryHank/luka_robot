"""Real tracker/worker/session integration for weak-ambiguity holds, no hardware."""
import unittest
from unittest import mock

from person_follow import test_worker_safety as fixtures


class WorkerAmbiguousHoldTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.WorkerStateSafetyTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.monitor = self.fixture.monitor
        self.track_id = self.fixture.track_id
        self.profile = self.fixture._known_profile()
        self.monitor.command('select', {'track_id': self.track_id})

    def hold_frame(self, now, single_weak=False):
        """Supply only invisible hold evidence, never ambiguous boxes as tracks."""
        fixture, monitor = self.fixture, self.monitor
        faces = mock.Mock()
        faces.face_features.side_effect = AssertionError('Invisible hold must not inspect a face')
        fixture.now = now
        detections = [dict(bbox=[9, 10, 79, 180], confidence=.3, depth_m=1.7)]
        if not single_weak:
            detections.append(dict(bbox=[11, 10, 81, 180], confidence=.31, depth_m=1.7))
        monitor.process_observations(detections, None, b'weak-ambiguous-frame',
                                     1700000000 + now, now, faces)
        faces.face_features.assert_not_called()
        self.assertEqual(monitor.tracker.last_events['hold_diagnostic_reason'],
                         'weak_runner_up_waiting_for_strong')
        return monitor.status()

    def strong_frame(self, now, with_face=False):
        self.fixture.now = now
        faces = mock.Mock()
        faces.face_features.return_value = ({
            'accepted': True, 'embedding': fixtures._embedding(),
            'face_bbox': [25, 15, 65, 60], 'quality': .95}
            if with_face else {'accepted': False, 'reason': 'no_face'})
        self.monitor.process_observations([
            dict(bbox=[10, 10, 80, 180], confidence=.8, depth_m=1.7)],
            None, b'strong-frame', 1700000000 + now, now, faces)
        return self.monitor.status()

    def test_invisible_ambiguity_hold_has_no_face_context_and_cancels_enrollment(self):
        monitor = self.monitor
        self.fixture._ready_enrollment(elapsed_s=16)
        public = self.hold_frame(100.1)
        session = public['target_session']
        self.assertEqual(public['tracks'], [])
        self.assertEqual(public['selected_track_id'], self.track_id)
        self.assertTrue(session['active'])
        self.assertEqual(session['state'], 'waiting_detection')
        self.assertEqual(session['profile_id'], self.profile['id'])
        self.assertFalse(session['visible'])
        self.assertFalse(session['current_face_verified'])
        self.assertFalse(session['motion_ready'])
        self.assertNotIn('person_id', session)
        self.assertNotIn('voice_profile_id', session)
        self.assertEqual(monitor.faces, {})
        self.assertEqual(monitor.recognizer._states, {})
        self.assertFalse(public['enrollment']['active'])
        self.assertEqual(public['enrollment']['reason'], 'target_lost')
        self.assertEqual([p['id'] for p in monitor.store.list_profiles()], [self.profile['id']])
        for action, payload in (
            ('select', {'track_id': self.track_id}),
            ('confirm-target', {'track_id': self.track_id, 'profile_id': self.profile['id']}),
            ('enroll', {'track_id': self.track_id, 'name': 'Must not save'}),
            ('finish-enrollment', {}),
        ):
            with self.subTest(action=action), self.assertRaises(ValueError):
                monitor.command(action, payload)

    def test_strong_return_keeps_historical_target_but_restarts_face_confirmation(self):
        self.hold_frame(100.1)
        public = self.strong_frame(100.2, with_face=True)
        row = public['tracks'][0]
        self.assertEqual(row['track_id'], self.track_id)
        self.assertEqual(row['observation_strength'], 'strong')
        # The held target label is retained, but a newly returned face starts
        # the recognizer's multi-frame evidence again rather than inheriting it.
        self.assertEqual(row['identity']['state'], 'unknown')
        self.assertEqual(row['identity']['reason'], 'confirming')
        self.assertNotIn('voice_profile_id', row['identity'])
        self.assertEqual(public['target_session']['profile_id'], self.profile['id'])
        self.assertEqual(public['target_session']['identity_basis'], 'face_then_body')
        self.assertTrue(public['target_session']['visible'])
        self.assertFalse(public['target_session']['current_face_verified'])
        self.assertEqual(self.monitor.recognizer._states[self.track_id]['count'], 1)

    def test_hold_frames_and_polls_do_not_extend_original_deadline(self):
        first = self.hold_frame(100.1)['target_session']
        second = self.hold_frame(100.4)['target_session']
        self.assertEqual(first['last_seen'], second['last_seen'])
        self.assertLess(second['hold_remaining_s'], first['hold_remaining_s'])
        self.fixture.now = 100.51
        expired = self.monitor.status()['target_session']
        self.assertFalse(expired['active'])
        self.assertIsNone(expired['profile_id'])
        self.assertEqual(expired['reason'], 'detection_hold_expired')
        public = self.strong_frame(100.55)
        self.assertFalse(public['target_session']['active'])
        self.assertIsNone(public['selected_track_id'])

    def test_single_clearer_weak_result_stays_invisible_until_strong_return(self):
        self.hold_frame(100.1)
        waiting = self.hold_frame(100.2, single_weak=True)
        self.assertEqual(waiting['tracks'], [])
        self.assertEqual(waiting['selected_track_id'], self.track_id)
        self.assertEqual(waiting['target_session']['state'], 'waiting_detection')
        self.assertEqual(waiting['target_session']['profile_id'], self.profile['id'])
        self.assertFalse(waiting['target_session']['visible'])
        returned = self.strong_frame(100.3)
        self.assertEqual(returned['tracks'][0]['track_id'], self.track_id)
        self.assertTrue(returned['target_session']['active'])
        self.assertTrue(returned['target_session']['visible'])

    def test_strong_ambiguous_return_clears_target_and_does_not_transfer_name(self):
        self.hold_frame(100.1)
        faces = mock.Mock()
        faces.face_features.return_value = {'accepted': False, 'reason': 'no_face'}
        self.fixture.now = 100.2
        self.monitor.process_observations([
            dict(bbox=[9, 10, 79, 180], confidence=.8, depth_m=1.7),
            dict(bbox=[11, 10, 81, 180], confidence=.8, depth_m=1.7)],
            None, b'conflicting-frame', 1700000100.2, 100.2, faces)
        public = self.monitor.status()
        self.assertIsNone(public['selected_track_id'])
        self.assertFalse(public['target_session']['active'])
        self.assertIsNone(public['target_session']['name'])
        self.assertTrue(all(row['association_ambiguous'] for row in public['tracks']))
        self.assertTrue(all(row['track_id'] != self.track_id for row in public['tracks']))
        self.assertTrue(all(row['identity']['state'] != 'matched' for row in public['tracks']))

    def test_deleting_held_profile_revokes_it_before_any_strong_return(self):
        self.hold_frame(100.1)
        self.monitor.command('delete-profile', {'id': self.profile['id']})
        self.assertEqual(self.monitor.target_session.status()['reason'], 'profile_deleted')
        target = self.monitor.status()['target_session']
        self.assertFalse(target['active'])
        self.assertIsNone(target['name'])
        public = self.strong_frame(100.2)
        self.assertFalse(public['target_session']['active'])
        self.assertIsNone(public['target_session']['name'])
        self.assertEqual(public['profiles'], [])


if __name__ == '__main__':
    unittest.main()
