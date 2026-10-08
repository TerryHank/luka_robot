"""Face-anchored clothing evidence can disambiguate, not assert identity."""
import unittest

import numpy as np

from person_follow.tracking import ConservativeTracker


def person(box):
    return dict(bbox=list(box), confidence=.8, depth_m=2.)


def vector(axis):
    result = np.zeros(512, dtype=np.float32)
    result[axis] = 1.
    return result


class FaceAnchoredAppearanceTests(unittest.TestCase):
    def anchored(self):
        tracker = ConservativeTracker(occlusion_reid=True)
        ident = tracker.update([person((40, 0, 140, 200))], 0., {0: vector(0)})[0]['track_id']
        tracker.select(ident)
        tracker.update([person((40, 0, 140, 200))], .1, {0: vector(0)})
        self.assertTrue(tracker.anchor_face_appearance(ident, vector(0), .11))
        tracker.update([person((40, 0, 140, 200))], .2, {0: vector(0)})
        self.assertTrue(tracker.anchor_face_appearance(ident, vector(0), .21))
        self.assertEqual(tracker.face_appearance_status(), dict(ready=True, samples=2))
        return tracker, ident

    def test_unique_appearance_resolves_two_geometric_candidates(self):
        tracker, ident = self.anchored()
        rows = tracker.update([person((0, 0, 100, 200)), person((80, 0, 180, 200))],
                              .3, {0: vector(1), 1: vector(0)})
        self.assertEqual(tracker.selected_track_id, ident)
        self.assertEqual(next(row['bbox'] for row in rows if row['track_id'] == ident),
                         [80., 0., 180., 200.])
        self.assertFalse(tracker.last_events['ambiguous'])

    def test_no_unique_descriptor_does_not_guess_between_people(self):
        tracker, _ = self.anchored()
        tracker.update([person((0, 0, 100, 200)), person((80, 0, 180, 200))],
                       .3, {0: vector(0), 1: vector(0)})
        self.assertIsNone(tracker.selected_track_id)
        self.assertTrue(tracker.last_events['ambiguous'])

    def test_face_anchor_requires_selected_strong_body_and_is_private(self):
        tracker, ident = self.anchored()
        self.assertFalse(tracker.anchor_face_appearance(ident + 1, vector(0), .22))
        self.assertFalse(any('embedding' in row for row in tracker._tracks.values()))
        tracker.clear_selection()
        self.assertEqual(tracker.face_appearance_status(), dict(ready=False, samples=0))


if __name__ == '__main__':
    unittest.main()
