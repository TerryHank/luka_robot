import unittest

from person_follow.face_reacquire import FaceReacquire


def person(track_id=3, profile='owner', score=.76, strength='strong'):
    return dict(track_id=track_id, observation_strength=strength,
                association_ambiguous=False,
                identity=dict(state='matched', id=profile, similarity=score))


def positioned(track_id, box, profile='owner'):
    return dict(person(track_id, profile), bbox=box)


class FaceReacquireTests(unittest.TestCase):
    def test_two_fresh_strong_face_matches_restore_only_same_profile(self):
        pending = FaceReacquire()
        pending.start('owner', 10.)
        self.assertFalse(pending.status(10.1)['motion_enabled'])
        self.assertIsNone(pending.observe([person()], set(), 10.2))
        self.assertIsNone(pending.observe([person(profile='stranger')], {3}, 10.3))
        self.assertIsNone(pending.observe([person()], {3}, 10.4))
        self.assertEqual(pending.observe([person()], {3}, 10.5), 3)
        self.assertFalse(pending.status(10.5)['active'])

    def test_ambiguous_or_weak_body_breaks_confirmation(self):
        pending = FaceReacquire()
        pending.start('owner', 0.)
        self.assertIsNone(pending.observe([person()], {3}, .1))
        self.assertIsNone(pending.observe([person(), person(4)], {3, 4}, .2))
        self.assertIsNone(pending.observe([person()], {3}, .3))
        self.assertIsNone(pending.observe([person(strength='weak')], {3}, .4))
        self.assertIsNone(pending.observe([person(score=.55)], {3}, .5))
        self.assertIsNone(pending.observe([person()], {3}, .6))
        self.assertEqual(pending.observe([person()], {3}, .7), 3)

    def test_other_person_in_view_does_not_block_unique_face_return(self):
        pending = FaceReacquire()
        pending.start('owner', 0.)
        owner = positioned(3, [0, 0, 100, 240])
        visitor = positioned(4, [300, 0, 400, 240], profile='visitor')
        self.assertIsNone(pending.observe([owner, visitor], {3, 4}, .1))
        self.assertEqual(pending.observe([owner, visitor], {3, 4}, .3), 3)

    def test_skipped_face_frame_with_two_separate_people_keeps_short_confirmation(self):
        pending = FaceReacquire()
        pending.start('owner', 0.)
        owner = positioned(3, [0, 0, 100, 240])
        visitor = positioned(4, [300, 0, 400, 240], profile='visitor')
        self.assertIsNone(pending.observe([owner, visitor], {3}, .1))
        self.assertIsNone(pending.observe([owner, visitor], {4}, .2))
        self.assertEqual(pending.observe([owner, visitor], {3}, .3), 3)

    def test_multiple_matches_or_overlapping_people_cannot_reacquire(self):
        owner = positioned(3, [0, 0, 100, 240])
        other = positioned(4, [300, 0, 400, 240])
        overlap = positioned(4, [50, 0, 150, 240], profile='visitor')
        for rows in ([owner, other], [owner, overlap]):
            pending = FaceReacquire()
            pending.start('owner', 0.)
            self.assertIsNone(pending.observe(rows, {3, 4}, .1))
            self.assertIsNone(pending.observe(rows, {3, 4}, .3))

    def test_expiry_cannot_be_extended_by_status_polling(self):
        pending = FaceReacquire(window_s=3.)
        pending.start('owner', 4.)
        self.assertTrue(pending.status(6.9)['active'])
        self.assertFalse(pending.status(7.01)['active'])
        self.assertIsNone(pending.observe([person()], {3}, 7.02))

    def test_skipped_face_frames_do_not_erase_two_fresh_confirmations(self):
        pending = FaceReacquire()
        pending.start('owner', 0.)
        self.assertIsNone(pending.observe([person()], {3}, .1))
        self.assertIsNone(pending.observe([person()], set(), .3))
        self.assertIsNone(pending.observe([person()], set(), .5))
        self.assertEqual(pending.observe([person()], {3}, .7), 3)

    def test_first_confirmation_expires_without_fresh_second_face(self):
        pending = FaceReacquire()
        pending.start('owner', 0.)
        self.assertIsNone(pending.observe([person()], {3}, .1))
        self.assertIsNone(pending.observe([person()], set(), 1.4))
        self.assertIsNone(pending.observe([person()], {3}, 1.5))
        self.assertEqual(pending.observe([person()], {3}, 1.6), 3)
