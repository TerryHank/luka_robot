"""Occlusion recovery is an internal producer proof, never a face match."""
import copy
import unittest

from person_follow.target_session import TargetSession


PROFILES = {'a': {'id': 'a', 'name': '主人'}, 'b': {'id': 'b', 'name': '访客'}}


def body(track_id=1, profile=None, **extra):
    identity = ({'state': 'matched', 'id': profile, 'name': PROFILES[profile]['name']}
                if profile else {'state': 'no_face', 'id': None, 'name': None})
    return dict(track_id=track_id, visible=True, observation_strength='strong',
                identity=identity, **extra)


def hold(now, anchor=100., **extra):
    result = dict(track_id=1, reason='occlusion_reid_wait', last_seen=anchor,
                  missing_age_s=now-anchor, deadline_mono=anchor+8.)
    result.update(extra)
    return result


def proof(now=102., anchor=100., **extra):
    result = dict(track_id=1, episode_last_seen=anchor, verified=True,
                  method='appearance_geometry_unique', recovered_mono=now, candidate_count=1)
    result.update(extra)
    return result


class TargetOcclusionTests(unittest.TestCase):
    def setUp(self):
        self.target = TargetSession()
        self.target.update([body(profile='a')], 1, 100., valid_profiles=PROFILES)

    def wait(self, now=100.2, **kwargs):
        options = dict(tracks=[], selected_track_id=1, now=now,
                       valid_profiles=PROFILES, hold=hold(now))
        options.update(kwargs)
        return self.target.update(**options)

    def recover(self, now=102., row=None, **kwargs):
        if row is None:
            row = body(recovery_proof=proof(now))
        options = dict(tracks=[row], selected_track_id=1, now=now, valid_profiles=PROFILES)
        options.update(kwargs)
        return self.target.update(**options)

    def test_fresh_camera_allows_invisible_wait_beyond_ordinary_miss_timeout(self):
        for now in (100.2, 100.8, 102.5):
            state = self.wait(now)
            self.assertTrue(state['active'])
            self.assertEqual(state['state'], 'waiting_occlusion')
            self.assertEqual(state['profile_id'], 'a')
            self.assertFalse(state['visible'])
            self.assertFalse(state['current_face_verified'])
            self.assertFalse(state['motion_ready'])
            self.assertFalse(state['motion_enabled'])
            self.assertFalse(state['confirmation_available'])
            self.assertEqual(state['last_seen'], 100.)
            self.assertAlmostEqual(state['hold_remaining_s'], 108.-now)
            for field in ('bbox', 'distance_m', 'face_bbox', 'person_id', 'voice_profile_id'):
                self.assertNotIn(field, state)

    def test_eight_second_deadline_expires_and_cannot_reacquire_same_id(self):
        self.wait()
        state = self.wait(108.01)
        self.assertFalse(state['active'])
        self.assertIsNone(state['name'])
        self.assertEqual(state['reason'], 'occlusion_hold_expired')
        self.assertFalse(self.recover(108.02)['active'])

    def test_chair_occlusion_keeps_identity_paused_without_motion_past_three_seconds(self):
        state = self.wait(104.2)
        self.assertTrue(state['active'])
        self.assertEqual(state['state'], 'waiting_occlusion')
        self.assertFalse(state['visible'])
        self.assertFalse(state['motion_ready'])
        self.assertAlmostEqual(state['hold_remaining_s'], 3.8)
        recovered = self.recover(104.4, row=body(recovery_proof=proof(104.4)))
        self.assertTrue(recovered['active'])
        self.assertEqual(recovered['track_id'], 1)
        self.assertEqual(recovered['profile_id'], 'a')
        self.assertFalse(recovered['motion_enabled'])

    def test_polls_cannot_refresh_anchor_or_extend_deadline(self):
        self.wait()
        state = self.wait(107.9)
        self.assertAlmostEqual(state['hold_remaining_s'], .1)
        for new_hold in (hold(107.95, anchor=100.5), hold(107.95, deadline_mono=109.)):
            with self.subTest(hold=new_hold):
                self.setUp()
                self.wait()
                state = self.wait(107.95, hold=new_hold)
                self.assertFalse(state['active'])

    def test_hold_kind_cannot_be_switched_to_extend_existing_wait(self):
        ordinary = dict(track_id=1, last_seen=100., missing_age_s=.2,
                        reason='temporary_detection_miss')
        self.target.update([], 1, 100.2, hold=ordinary, valid_profiles=PROFILES)
        self.assertFalse(self.wait(100.3)['active'])
        self.setUp()
        self.wait()
        ordinary['missing_age_s'] = .3
        state = self.target.update([], 1, 100.3, hold=ordinary, valid_profiles=PROFILES)
        self.assertFalse(state['active'])

    def test_verified_same_episode_strong_recovery_keeps_only_historical_identity(self):
        self.wait()
        row = body(recovery_proof=proof())
        original = copy.deepcopy(row)
        state = self.recover(row=row)
        self.assertEqual(row, original)
        self.assertTrue(state['active'])
        self.assertTrue(state['visible'])
        self.assertEqual(state['track_id'], 1)
        self.assertEqual(state['profile_id'], 'a')
        self.assertEqual(state['identity_basis'], 'face_then_body')
        self.assertFalse(state['current_face_verified'])
        self.assertEqual(row['identity']['state'], 'no_face')
        self.assertIsNone(state['hold_remaining_s'])
        self.assertNotIn('recovery_proof', state)
        # Proof is needed at reacquisition, not on every subsequently continuous
        # observation of the already recovered body.
        self.assertTrue(self.recover(102.1, row=body())['active'])

    def test_manual_target_recovery_does_not_gain_face_verification(self):
        self.target.reset('selected')
        self.target.update([body()], 1, 100., valid_profiles=PROFILES)
        self.target.confirm(1, 'a', PROFILES, 100.01)
        self.wait()
        state = self.recover()
        self.assertEqual(state['confirmation_source'], 'user_selection')
        self.assertFalse(state['face_verified'])
        self.assertFalse(state['current_face_verified'])

    def test_missing_forged_old_or_ambiguous_proof_cannot_resume(self):
        bad_proofs = (None, {}, proof(verified=False), proof(verified=1),
            proof(method='geometry_only'), proof(track_id=2), proof(track_id=True),
            proof(anchor=99.), proof(recovered_mono=100.1), proof(recovered_mono=102.1),
            proof(recovered_mono=float('nan')), proof(recovered_mono=10**1000),
            proof(episode_last_seen=float('inf')),
            proof(candidate_count=2), proof(candidate_count=0), proof(candidate_count=True))
        for bad in bad_proofs:
            with self.subTest(proof=bad):
                self.setUp()
                self.wait()
                state = self.recover(row=body(recovery_proof=bad))
                self.assertFalse(state['active'])
                self.assertIsNone(state['name'])
                self.assertEqual(state['reason'], 'occlusion_recovery_unverified')
                self.assertFalse(self.recover(102.1)['active'])

    def test_weak_invisible_or_ambiguous_recovery_row_is_rejected(self):
        for field, value in (('observation_strength', 'weak'), ('visible', False),
                             ('association_ambiguous', True)):
            with self.subTest(field=field):
                self.setUp()
                self.wait()
                row = body(recovery_proof=proof())
                row[field] = value
                self.assertFalse(self.recover(row=row)['active'])

    def test_exact_deadline_recovery_is_allowed_but_not_after_it(self):
        self.wait()
        self.assertTrue(self.recover(108., row=body(recovery_proof=proof(108.)))['active'])
        self.assertTrue(self.recover(108.1, row=body())['active'])
        self.setUp()
        self.wait()
        self.assertFalse(self.recover(108.0001)['active'])

    def test_confirm_during_valid_occlusion_rejects_without_erasing_wait(self):
        self.wait(102.)
        with self.assertRaisesRegex(ValueError, 'temporarily missing'):
            self.target.confirm(1, 'a', PROFILES, 102.1)
        state = self.target.status()
        self.assertTrue(state['active'])
        self.assertEqual(state['state'], 'waiting_occlusion')
        self.assertEqual(state['profile_id'], 'a')
        with self.assertRaises(ValueError):
            self.target.confirm(1, 'a', PROFILES, 108.1)
        self.assertFalse(self.target.status()['active'])

    def test_camera_stale_deleted_profile_or_ambiguous_hold_clear_immediately(self):
        for kwargs in (dict(fresh=False), dict(valid_profiles={}),
                       dict(hold=hold(102., ambiguous=True))):
            with self.subTest(kwargs=kwargs):
                self.setUp()
                self.wait()
                state = self.wait(102., **kwargs)
                self.assertFalse(state['active'])
                self.assertIsNone(state['profile_id'])
                self.assertFalse(self.recover(102.1)['active'])

    def test_explicit_face_conflict_clears_even_with_valid_appearance_proof(self):
        self.wait()
        state = self.recover(row=body(profile='b', recovery_proof=proof()))
        self.assertFalse(state['active'])
        self.assertEqual(state['reason'], 'identity_conflict')
        self.assertIsNone(state['name'])

    def test_unrelated_visible_person_does_not_become_the_waiting_target(self):
        state = self.wait(101., tracks=[body(2, profile='b')])
        self.assertTrue(state['active'])
        self.assertEqual(state['state'], 'waiting_occlusion')
        self.assertEqual(state['profile_id'], 'a')
        self.assertEqual(state['track_id'], 1)
        self.assertFalse(state['current_face_verified'])

    def test_unlock_or_new_selection_cannot_restore_old_target_metadata(self):
        self.wait()
        self.target.reset('unlocked')
        state = self.recover(selected_track_id=None)
        self.assertFalse(state['active'])
        self.assertIsNone(state['name'])
        self.setUp()
        self.wait()
        other = self.recover(row=body(2), selected_track_id=2)
        self.assertTrue(other['active'])
        self.assertEqual(other['track_id'], 2)
        self.assertIsNone(other['profile_id'])

    def test_previous_episode_proof_cannot_resume_a_later_occlusion(self):
        self.wait()
        self.recover()
        later_hold = hold(102.2, anchor=102.)
        self.target.update([], 1, 102.2, hold=later_hold, valid_profiles=PROFILES)
        state = self.recover(104., row=body(recovery_proof=proof(104., anchor=100.)))
        self.assertFalse(state['active'])
        self.assertEqual(state['reason'], 'occlusion_recovery_unverified')

    def test_hold_cannot_create_new_target_or_accept_malformed_deadline(self):
        self.target.reset('selected')
        self.assertFalse(self.wait()['active'])
        for bad in (hold(100.2, deadline_mono=104.), hold(100.2, deadline_mono=float('inf')),
                    hold(100.2, deadline_mono=10**1000),
                    hold(100.2, missing_age_s=9.), hold(100.2, last_seen=100.3)):
            with self.subTest(hold=bad):
                self.setUp()
                self.assertFalse(self.wait(hold=bad)['active'])


if __name__ == '__main__':
    unittest.main()
