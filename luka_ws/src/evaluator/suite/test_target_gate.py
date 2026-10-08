import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2] / "control/luka_person_following"
sys.path.insert(0, str(ROOT))
from luka_person_following.target_gate import selected_target


def row(**patch):
    base = dict(
        track_id=12, bbox=[200, 80, 400, 450],
        confidence=.9, visible=True, observation_strength="strong",
        association_ambiguous=False, depth_valid=True,
        seg_depth_trimmed_mean=True, position_optical_m=[.1, 0., 3.],
        width_m=.5, height_m=1.7)
    base["class"] = "person"
    base.update(patch)
    return base


class TargetGateTest(unittest.TestCase):
    def test_selected_only(self):
        selected, reason, ident = selected_target(
            [row(), row(track_id=99, confidence=.99)], 12, .1)
        self.assertEqual(reason, "selected_seg_depth_valid")
        self.assertEqual(ident, 12)
        self.assertEqual(selected["track_id"], 12)

    def test_fail_closed_conditions(self):
        cases = [
            ([row()], 12, .6, "stale_frame"),
            ([row()], None, .1, "unselected"),
            ([row()], 99, .1, "selected_missing"),
            ([row(visible=False)], 12, .1, "selected_ambiguous_or_weak"),
            ([row(association_ambiguous=True)], 12, .1, "selected_ambiguous_or_weak"),
            ([row(observation_strength="weak")], 12, .1, "selected_ambiguous_or_weak"),
            ([row(depth_valid=False)], 12, .1, "invalid_seg_depth"),
            ([row(seg_depth_trimmed_mean=False)], 12, .1, "invalid_seg_depth_method"),
            ([row(width_m=.2)], 12, .1, "official_target_filter"),
            ([row(confidence=.49)], 12, .1, "official_target_filter"),
        ]
        for rows, ident, age, expected in cases:
            with self.subTest(expected=expected):
                selected, reason, _ = selected_target(rows, ident, age)
                self.assertIsNone(selected)
                self.assertEqual(reason, expected)

    def test_auto_mode_requires_exactly_one_person(self):
        selected, _, ident = selected_target(
            [row()], None, .1, auto_select_first_person=True)
        self.assertEqual(ident, 12)
        self.assertEqual(selected["track_id"], 12)
        selected, reason, _ = selected_target(
            [row(), row(track_id=13)], None, .1, auto_select_first_person=True)
        self.assertIsNone(selected)
        self.assertEqual(reason, "unselected")


if __name__ == "__main__":
    unittest.main()
