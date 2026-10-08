"""Geometry-only loss diagnostics use temporary files; no camera/model/network."""
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock

from person_follow import test_worker_safety as fixtures


worker = fixtures.worker
Recorder = worker.TrackingEventRecorder


def track(ident=1):
    return dict(track_id=ident, bbox=[1, 2, 30, 80], confidence=.8, depth_m=1.7,
                last_seen=1., last_strong_seen=.9, observation_strength='strong', visible=True)


class TrackingRecorderTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'diagnostics' / 'tracking_event.json'
        self.recorder = Recorder(self.path)

    def append(self, now, old=(1,), new=(1,), selected_before=None, selected_after=None):
        before = self.recorder.snapshot([track(i) for i in old], selected_before, old,
                                        [track(i) for i in old])
        after = self.recorder.snapshot([track(i) for i in new], selected_after, new,
                                       [track(i) for i in new])
        return self.recorder.record(detections=[track(i) for i in new], before=before, after=after,
                                    events={}, frame_mono=now-.02, processed_mono=now)

    def load(self):
        return json.loads(self.path.read_text(encoding='utf-8'))

    def test_stable_frames_update_ring_without_any_file_io(self):
        with mock.patch.object(worker.os, 'replace') as replace:
            for now in (1, 1.1, 1.2):
                self.assertFalse(self.append(now))
            replace.assert_not_called()
        self.assertEqual(len(self.recorder.frames), 3)
        self.assertFalse(self.path.parent.exists())

    def test_id_change_triggers_without_any_selected_person(self):
        self.append(1)
        self.assertTrue(self.append(2, new=(2,)))
        payload = self.load()
        self.assertIn('visible_id_changed', payload['trigger']['reasons'])
        self.assertIsNone(payload['trigger']['selected_before'])
        self.assertIsNone(payload['trigger']['selected_after'])
        self.assertEqual(len(payload['frames']), 2)
        self.assertEqual(payload['frames'][-1]['before']['tracks'][0]['track_id'], 1)
        self.assertEqual(payload['frames'][-1]['after']['tracks'][0]['track_id'], 2)
        self.assertEqual(payload['frames'][-1]['before']['retained_tracks'][0]['last_strong_seen'], .9)
        self.assertEqual(payload['frames'][-1]['before']['retained_tracks'][0]['last_seen'], 1.)

    def test_selection_loss_triggers_even_when_same_body_is_still_visible(self):
        self.assertTrue(self.append(1, selected_before=1, selected_after=None))
        self.assertEqual(self.load()['trigger']['reasons'], ['selected_cleared'])

    def test_unselected_retirements_never_overwrite_selected_loss_copy(self):
        selected_path = self.path.with_name('tracking_selected_loss.json')
        self.assertTrue(self.append(1, new=(2,), selected_before=1))
        selected_payload = selected_path.read_bytes()
        self.assertEqual(selected_payload, self.path.read_bytes())
        self.assertTrue(self.append(2.1, old=(2,), new=(3,)))
        self.assertTrue(self.append(3.2, old=(3,), new=(4,)))
        self.assertEqual(selected_path.read_bytes(), selected_payload)
        self.assertNotEqual(self.path.read_bytes(), selected_payload)
        self.assertTrue(self.append(3.3, old=(4,), new=(5,), selected_before=4))
        refreshed = json.loads(selected_path.read_text(encoding='utf-8'))
        self.assertEqual(refreshed['trigger']['selected_before'], 4)
        self.assertEqual(refreshed['trigger']['processed_mono'], 3.3)

    def test_selected_loss_bypasses_general_throttle_without_changing_its_timer(self):
        selected_path = self.path.with_name('tracking_selected_loss.json')
        self.assertTrue(self.append(1, new=(2,)))
        self.assertFalse(selected_path.exists())
        original = self.path.read_bytes()
        self.assertTrue(self.append(1.2, old=(2,), new=(3,), selected_before=2))
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.recorder.last_attempt_mono, 1)
        self.assertEqual(self.recorder.last_written_mono, 1)
        critical = json.loads(selected_path.read_text(encoding='utf-8'))
        self.assertIn('selected_cleared', critical['trigger']['reasons'])
        self.assertEqual(critical['trigger']['processed_mono'], 1.2)
        self.assertFalse(self.append(1.9, old=(3,), new=(4,)))
        self.assertTrue(self.append(2.05, old=(4,), new=(5,)))
        self.assertEqual(self.load()['trigger']['processed_mono'], 2.05)
        self.assertEqual(json.loads(selected_path.read_text(encoding='utf-8')), critical)

    def test_selected_copy_uses_atomic_private_write(self):
        selected_path = self.path.with_name('tracking_selected_loss.json')
        self.append(1, new=(2,))
        with mock.patch.object(worker.os, 'chmod', wraps=worker.os.chmod) as chmod:
            self.assertTrue(self.append(1.2, old=(2,), new=(3,), selected_before=2))
        chmod.assert_called_once_with(mock.ANY, 0o600)
        self.assertEqual(list(self.path.parent.glob('.tracking_event-*.tmp')), [])
        if os.name != 'nt':
            self.assertEqual(stat.S_IMODE(selected_path.stat().st_mode), 0o600)

    def test_retiring_unselected_invisible_history_also_triggers(self):
        before = self.recorder.snapshot([], None, [1], [track()])
        after = self.recorder.snapshot([], None, [])
        self.assertTrue(self.recorder.record(detections=[], before=before, after=after,
            events={'retired_ids': [1]}, frame_mono=1, processed_mono=1))
        self.assertEqual(self.load()['trigger']['reasons'], ['track_retired'])

    def test_ring_has_hard_frame_count_and_time_window_limits(self):
        for index in range(220):
            self.append(index*.05)
        self.assertEqual(len(self.recorder.frames), 160)
        self.assertAlmostEqual(self.recorder.frames[0]['processed_mono'], 3.)
        self.recorder = Recorder(self.path)
        for now in range(0, 31, 5):
            self.append(now)
        self.assertEqual([row['processed_mono'] for row in self.recorder.frames], [10, 15, 20, 25, 30])
        self.assertFalse(self.path.exists())

    def test_sensitive_fields_are_not_admitted_to_ring_or_saved_json(self):
        secret = dict(track(), identity={'id': 'PRIVATE-FACE-UUID', 'name': 'PRIVATE-NAME'},
                      embedding='PRIVATE-EMBEDDING', frame_jpeg_base64='PRIVATE-IMAGE',
                      voice_profile_id='PRIVATE-SPEAKER-UUID')
        before = dict(tracks=[secret], retained_tracks=[secret], retained_ids=[1],
                      selected_track_id=None, name='PRIVATE-SNAPSHOT-NAME')
        after = self.recorder.snapshot([track(2)], None, [2])
        events = dict(retired_ids=[1, 'PRIVATE-FACE-UUID'], name='PRIVATE-EVENT-NAME',
                      selected_hold=dict(track_id=1, last_seen=1, missing_age_s=.2,
                                         reason='PRIVATE-HOLD-NAME', name='PRIVATE-NAME'))
        self.assertTrue(self.recorder.record(detections=[secret], before=before, after=after,
                         events=events, frame_mono=1, processed_mono=1))
        for text in (self.path.read_text(encoding='utf-8'), json.dumps(list(self.recorder.frames))):
            self.assertNotIn('PRIVATE-', text)
            self.assertNotIn('embedding', text)
            self.assertNotIn('frame_jpeg', text)
            self.assertNotIn('voice_profile', text)
        self.assertEqual(self.load()['frames'][0]['detections'][0]['bbox'], [1., 2., 30., 80.])

    def test_nonfinite_values_are_replaced_before_strict_json_serialization(self):
        bad = dict(track(), bbox=[1, 2, float('nan'), 80], confidence=float('inf'))
        before = self.recorder.snapshot([bad], None, [1])
        self.assertTrue(self.recorder.record(detections=[bad], before=before,
            after=self.recorder.snapshot([track(2)], None, [2]), events={},
            frame_mono=float('nan'), processed_mono=1))
        row = self.load()['frames'][0]
        self.assertIsNone(row['frame_mono'])
        self.assertIsNone(row['detections'][0]['bbox'])
        self.assertIsNone(row['detections'][0]['confidence'])

    def test_trigger_writes_at_most_once_per_second_but_ring_keeps_updating(self):
        self.assertTrue(self.append(1, new=(2,)))
        original = self.path.read_bytes()
        self.assertFalse(self.append(1.2, old=(2,), new=(3,)))
        self.assertFalse(self.append(1.8, old=(3,), new=(4,)))
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(len(self.recorder.frames), 3)
        self.assertTrue(self.append(2.1, old=(4,), new=(5,)))
        self.assertEqual(len(self.load()['frames']), 4)

    def test_atomic_replace_sets_private_mode_and_cleans_temporary_files(self):
        with mock.patch.object(worker.os, 'chmod', wraps=worker.os.chmod) as chmod:
            self.assertTrue(self.append(1, new=(2,)))
        chmod.assert_called_once_with(mock.ANY, 0o600)
        self.assertEqual(list(self.path.parent.glob('.tracking_event-*.tmp')), [])
        if os.name != 'nt':
            self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)

    def test_write_failure_preserves_previous_file_is_throttled_and_does_not_raise(self):
        self.append(1, new=(2,))
        original = self.path.read_bytes()
        with mock.patch.object(worker.os, 'replace', side_effect=OSError('disk full')) as replace:
            self.assertFalse(self.append(2.1, old=(2,), new=(3,)))
            self.assertFalse(self.append(2.2, old=(3,), new=(4,)))
            self.assertEqual(replace.call_count, 1)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(self.path.parent.glob('.tracking_event-*.tmp')), [])
        self.assertEqual(self.recorder.last_error, 'OSError')


class WorkerDiagnosticIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.WorkerStateSafetyTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.monitor = self.fixture.monitor
        self.path = Path(self.fixture.directory.name) / 'diagnostics' / 'tracking_event.json'
        self.monitor.tracking_recorder = Recorder(self.path)

    def test_real_unselected_tracker_id_change_writes_geometry_diagnostics(self):
        self.fixture._known_profile()
        self.fixture.now = 100.1
        faces = mock.Mock()
        faces.face_features.return_value = {'accepted': False, 'reason': 'no_face'}
        self.assertTrue(self.monitor.process_observations([
            dict(bbox=[300, 10, 370, 180], confidence=.9, depth_m=1.7)],
            None, b'private-image-never-saved', 1700000100.1, 100.1, faces))
        payload = json.loads(self.path.read_text(encoding='utf-8'))
        self.assertIn('visible_id_changed', payload['trigger']['reasons'])
        self.assertIsNone(payload['trigger']['selected_before'])
        self.assertIsNone(payload['trigger']['selected_after'])
        self.assertNotIn('Known person', self.path.read_text(encoding='utf-8'))
        self.assertNotIn('private-image', self.path.read_text(encoding='utf-8'))
        retained = payload['frames'][-1]['before']['retained_tracks'][0]
        self.assertEqual(retained['bbox'], [10., 10., 80., 180.])
        self.assertAlmostEqual(retained['last_strong_seen'], 99.9)

    def test_camera_stale_invalidation_records_reset_before_after_and_fixed_reason(self):
        profile = self.fixture._known_profile()
        self.monitor.command('select', {'track_id': self.fixture.track_id})
        self.fixture.now = 101
        public = self.monitor.status()
        self.assertEqual(public['tracks'], [])
        payload = json.loads(self.path.read_text(encoding='utf-8'))
        last = payload['frames'][-1]
        self.assertEqual(last['outcome'], 'invalidated')
        self.assertEqual(last['invalidation_reason'], 'camera_stale')
        self.assertEqual(last['before']['selected_track_id'], self.fixture.track_id)
        self.assertIsNone(last['after']['selected_track_id'])
        self.assertEqual(last['after']['retained_ids'], [])
        self.assertNotIn(profile['id'], self.path.read_text(encoding='utf-8'))
        self.assertEqual([p['id'] for p in self.monitor.store.list_profiles()], [profile['id']])

    def test_processing_delay_records_current_detection_timestamp_without_raw_error(self):
        self.monitor.command('select', {'track_id': self.fixture.track_id})
        self.fixture.now = 101
        detections = [dict(bbox=[10, 10, 80, 180], confidence=.9, depth_m=1.7)]
        self.monitor.invalidate('本帧处理延迟过高，PRIVATE-RAW-MESSAGE',
                                diagnostic_detections=detections, diagnostic_frame_mono=100.2)
        last = json.loads(self.path.read_text(encoding='utf-8'))['frames'][-1]
        self.assertEqual(last['invalidation_reason'], 'processing_delay')
        self.assertEqual(last['frame_mono'], 100.2)
        self.assertEqual(last['detections'][0]['confidence'], .9)
        self.assertNotIn('PRIVATE-', self.path.read_text(encoding='utf-8'))

    def test_unexpected_diagnostic_exception_does_not_change_frame_result(self):
        self.fixture.now = 100.1
        faces = mock.Mock()
        faces.face_features.return_value = {'accepted': False, 'reason': 'no_face'}
        with mock.patch.object(self.monitor.tracking_recorder, 'record', side_effect=RuntimeError('diagnostic only')):
            self.assertTrue(self.monitor.process_observations([
                dict(bbox=[10, 10, 80, 180], confidence=.9, depth_m=1.7)],
                None, b'frame', 1700000100.1, 100.1, faces))
        self.assertEqual(self.monitor.tracks[0]['track_id'], self.fixture.track_id)
        self.assertEqual(self.monitor.jpeg, b'frame')
        self.assertIsNone(self.monitor.error)


if __name__ == '__main__':
    unittest.main()
