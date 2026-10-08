import unittest
from concurrent.futures import Future

from nx_voice_follow import (DASHBOARD, PEOPLE, VoiceFollowCoordinator,
                             matching_face, speaker_id)


VOICE = 'owner-voice'
FACE = 'owner-face'


def state(frame, identity=None, ambiguous=False):
    identity = identity or {'state': 'matched', 'id': FACE,
                            'voice_profile_id': VOICE}
    return {'active': True, 'loading': False, 'error': None,
            'camera_age': .1, 'frame_at': frame, 'enrollment': {'active': False},
            'tracks': [{'track_id': 7, 'visible': True,
                        'association_ambiguous': ambiguous,
                        'observation_strength': 'strong', 'identity': identity}],
            'target_session': {'active': True, 'visible': True, 'track_id': 7,
                               'profile_id': FACE, 'face_verified': True,
                               'confirmation_source': 'face_match'}}


class VoiceFollowTests(unittest.TestCase):
    def test_current_speaker_and_short_phrase_threshold(self):
        speaker = {'state': 'candidate', 'profile_id': VOICE,
                   'similarity': .8, 'audio_s': 1.2}
        self.assertIsNone(speaker_id(speaker, 100, 105))
        speaker['similarity'] = .84
        self.assertEqual(speaker_id(speaker, 100, 105), VOICE)
        speaker['audio_s'] = .7
        self.assertIsNone(speaker_id(speaker, 100, 105))
        speaker['similarity'] = .86
        self.assertEqual(speaker_id(speaker, 100, 105), VOICE)
        self.assertIsNone(speaker_id(speaker, 100, 116))

    def test_only_fresh_unique_linked_face(self):
        self.assertEqual(matching_face(state(1), VOICE), (7, FACE))
        self.assertIsNone(matching_face(state(1), 'other'))
        self.assertIsNone(matching_face(state(1, ambiguous=True), VOICE))
        stale = state(1)
        stale['camera_age'] = 1.0
        self.assertIsNone(matching_face(stale, VOICE))
        duplicate = state(1)
        duplicate['tracks'].append(dict(duplicate['tracks'][0], track_id=8))
        self.assertIsNone(matching_face(duplicate, VOICE))

    def test_voice_face_auto_select_then_existing_motion_gate(self):
        calls, messages = [], []
        frames = [state(1), state(2), state(3)]
        def api(url, body=None):
            calls.append((url, body))
            if url == PEOPLE + 'follow-state':
                return frames.pop(0) if len(frames) > 1 else frames[0]
            if url == PEOPLE + 'select':
                return {'ok': True}
            if url == DASHBOARD + 'stop':
                return {'ok': True}
            if url == DASHBOARD + 'start':
                return {'ok': True}
            raise AssertionError(url)
        tick = [0.]
        def sleep(dt):
            tick[0] += dt
        coordinator = VoiceFollowCoordinator(messages.append, get=api,
                                              clock=lambda: tick[0], sleep=sleep)
        future = Future()
        future.set_result({'state': 'candidate', 'profile_id': VOICE,
                           'similarity': .85, 'audio_s': 1.2})
        import unittest.mock
        with unittest.mock.patch('nx_voice_follow.time.time', return_value=105):
            coordinator._run(0, future, 100)
        self.assertIn((PEOPLE + 'select', {'track_id': 7}), calls)
        self.assertLess(calls.index((DASHBOARD + 'stop', {})),
                        calls.index((PEOPLE + 'select', {'track_id': 7})))
        self.assertIn((DASHBOARD + 'start', {}), calls)
        self.assertTrue(any('开始跟随' in message for message in messages))

    def test_unverified_speaker_never_selects_or_moves(self):
        calls, messages = [], []
        coordinator = VoiceFollowCoordinator(messages.append,
                                              get=lambda *args: calls.append(args))
        future = Future()
        future.set_result({'state': 'unknown'})
        import unittest.mock
        with unittest.mock.patch('nx_voice_follow.time.time', return_value=105):
            coordinator._run(0, future, 100)
        self.assertEqual(calls, [])
        self.assertTrue(any('声纹' in message for message in messages))


if __name__ == '__main__':
    unittest.main()
