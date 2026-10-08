import unittest

from nx_follow_acquire import FollowAcquisition, live_track, matched_profile


def frame(stamp, match=True, selected=4):
    return dict(active=True, loading=False, error=None, camera_age=.1,
                frame_at=stamp, selected_track_id=selected,
                tracks=[dict(track_id=4, visible=True, association_ambiguous=False,
                             observation_strength='strong',
                             identity={'state': 'matched' if match else 'unknown',
                                       'id': 'face-owner' if match else None})])


class FakeController:
    def __init__(self):
        self.command_epoch = 0
        self.starts = []

    def stop(self, reason='stopped'):
        self.command_epoch += 1

    def start(self, **kwargs):
        self.starts.append(kwargs)
        return {'enabled': True}


class AcquisitionTests(unittest.TestCase):
    def test_live_track_rejects_stale_and_ambiguous(self):
        self.assertIsNotNone(live_track(frame(1), 4))
        fresh_slow = frame(1)
        fresh_slow['camera_age'] = .8
        self.assertIsNotNone(live_track(fresh_slow, 4))
        stale = frame(1)
        stale['camera_age'] = .91
        self.assertIsNone(live_track(stale, 4))
        ambiguous = frame(1)
        ambiguous['tracks'][0]['association_ambiguous'] = True
        self.assertIsNone(live_track(ambiguous, 4))
        self.assertIsNone(matched_profile(frame(1, match=False), 'face-owner'))

    def test_profile_selection_needs_two_new_face_frames(self):
        controller = FakeController()
        states = [frame(1), frame(2)]
        calls = []
        def api(path, body=None):
            calls.append((path, body))
            if path == 'follow-state':
                return states.pop(0) if len(states) > 1 else states[0]
            return {'ok': True}
        tick = [0.]
        def sleep(seconds):
            tick[0] += seconds
        acquire = FollowAcquisition(controller, request=api,
                                    clock=lambda: tick[0], sleep=sleep)
        acquire._run(0, 0, 'profile', 'face-owner')
        self.assertIn(('select', {'track_id': 4}), calls)
        self.assertEqual(controller.starts[0]['expected_profile_id'], 'face-owner')
        self.assertIsNone(controller.starts[0]['expected_track_id'])
        self.assertEqual(acquire.status()['phase'], 'following')

    def test_stop_epoch_prevents_late_start(self):
        controller = FakeController()
        states = [frame(1), frame(2)]
        tick = [0.]
        def sleep(seconds):
            tick[0] += seconds
            controller.stop()
        acquire = FollowAcquisition(controller,
                                    request=lambda path, body=None: states[0],
                                    clock=lambda: tick[0], sleep=sleep)
        acquire._run(0, 0, 'track', 4)
        self.assertEqual(controller.starts, [])

    def test_status_does_not_claim_following_after_base_stopped(self):
        controller = FakeController()
        controller.enabled = False
        controller.reason = '网页遥控接管'
        acquire = FollowAcquisition(controller)
        acquire.phase = 'following'
        self.assertEqual(acquire.status(),
                         {'phase': 'idle', 'message': '网页遥控接管', 'mode': None})


if __name__ == '__main__':
    unittest.main()
