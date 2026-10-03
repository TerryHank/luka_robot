import copy
import unittest
from luka_person_following.selection import selected_observation


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.state = dict(active=True, camera_age=.1, selected_track_id=12, tracks=[
            dict(track_id=12, confidence=.9, bbox=[200,80,400,450], visible=True,
                 observation_strength='strong', association_ambiguous=False, depth_valid=True,
                 depth_diagnostic=dict(method='seg_valid_arithmetic_mean',
                     position_optical_m=[.1,0,3], width_m=.5, height_m=1.7)),
            dict(track_id=99, confidence=.99)])

    def test_other_person_never_selected(self):
        row, _ = selected_observation(self.state)
        self.assertEqual(row['track_id'], 12)
        self.state['tracks'].pop(0)
        self.assertIsNone(selected_observation(self.state)[0])

    def test_unlock_and_stale(self):
        for patch in [dict(selected_track_id=None), dict(camera_age=.6), dict(active=False)]:
            state = dict(self.state, **patch)
            self.assertIsNone(selected_observation(state)[0])
        self.assertIsNone(selected_observation(self.state, .5)[0])

    def test_ambiguous_weak_and_invalid_depth(self):
        for patch in [dict(association_ambiguous=True), dict(observation_strength='weak'),
                      dict(visible=False), dict(depth_valid=False)]:
            state = copy.deepcopy(self.state)
            state['tracks'][0].update(patch)
            self.assertIsNone(selected_observation(state)[0])

    def test_no_bbox_depth_fallback(self):
        self.state['tracks'][0]['depth_diagnostic']['method'] = 'bbox_median'
        self.assertIsNone(selected_observation(self.state)[0])


if __name__ == '__main__':
    unittest.main()
