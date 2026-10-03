import copy
import unittest
from unittest.mock import Mock

from person_follow.detection_cleanup import consolidate_people


def body(box, depth=1.1, confidence=.47, **extra):
    return dict(bbox=list(box), depth_m=depth, confidence=confidence, **extra)


LARGE = [121, 36, 518, 471]
SMALL = [134, 38, 411, 260]


class NestedDetectionCleanupTests(unittest.TestCase):
    def test_observed_duplicate_keeps_large_geometry_for_either_confidence_order(self):
        for reverse in (False, True):
            for large_score, small_score in ((.48, .46), (.46, .48)):
                with self.subTest(reverse=reverse, scores=(large_score, small_score)):
                    large = body(LARGE, 1.1, large_score, distance_m=1.1, bearing_rad=.1)
                    small = body(SMALL, 1.2, small_score, distance_m=1.2, bearing_rad=.2)
                    rows = [large, small][::(-1 if reverse else 1)]
                    before = copy.deepcopy(rows)
                    result = consolidate_people(rows, lambda _: 0)
                    self.assertEqual(rows, before)
                    self.assertEqual(len(result), 1)
                    self.assertEqual(result[0]["bbox"], LARGE)
                    self.assertEqual(result[0]["depth_m"], 1.1)
                    self.assertEqual(result[0]["distance_m"], 1.1)
                    self.assertEqual(result[0]["bearing_rad"], .1)
                    self.assertEqual(result[0]["confidence"], .48)
                    self.assertTrue(result[0]["duplicate_consolidated"])
                    self.assertEqual(result[0]["duplicate_boxes"], 1)
                    result[0]["bbox"][0] = -999
                    self.assertEqual(rows, before)

    def test_person_and_chair_at_different_depth_do_not_merge(self):
        counter = Mock(return_value=1)
        rows = [body(LARGE, 2), body(SMALL, 1.1)]
        self.assertEqual(consolidate_people(rows, counter), rows)
        counter.assert_not_called()

    def test_two_faces_forbid_merge_even_at_similar_depth(self):
        rows = [body(LARGE), body(SMALL)]
        self.assertEqual(consolidate_people(rows, lambda _: 2), rows)

    def test_missing_depth_requires_exactly_one_face(self):
        for depths in ((None, None), (1.1, None), (None, 1.1)):
            rows = [body(LARGE, depths[0]), body(SMALL, depths[1])]
            for count in (None, 0, 2, True, 1.0, -1):
                with self.subTest(depths=depths, count=count):
                    self.assertEqual(consolidate_people(rows, lambda _: count), rows)
            self.assertEqual(consolidate_people(rows), rows)
            self.assertEqual(len(consolidate_people(rows, lambda _: 1)), 1)

    def test_unknown_larger_depth_is_not_borrowed_from_smaller(self):
        large = body(LARGE, None, distance_m=None, depth_valid=False, bearing_rad=None)
        small = body(SMALL, 1.1, distance_m=1.1, depth_valid=True, bearing_rad=.3)
        result = consolidate_people([small, large], lambda _: 1)[0]
        for key in ("depth_m", "distance_m", "bearing_rad"):
            self.assertIsNone(result[key])
        self.assertFalse(result["depth_valid"])

    def test_explicit_invalid_depth_does_not_count_as_evidence(self):
        rows = [body(LARGE, 1.1, depth_valid=False), body(SMALL)]
        self.assertEqual(consolidate_people(rows, lambda _: 0), rows)

    def test_nonfinite_or_nonpositive_depth_is_unknown(self):
        for bad in (float("nan"), float("inf"), 0, -1, "bad"):
            rows = [body(LARGE, bad), body(SMALL)]
            self.assertEqual(len(consolidate_people(rows, lambda _: 0)), 2)

    def test_known_similar_depth_can_merge_without_face_counter(self):
        self.assertEqual(len(consolidate_people([body(LARGE), body(SMALL, 1.3)])), 1)

    def test_same_size_overlap_and_crossing_are_not_nested_duplicates(self):
        counter = Mock(return_value=1)
        for boxes in (([0, 0, 100, 200], [15, 0, 115, 200]),
                      ([0, 0, 100, 200], [40, 0, 115, 120]),
                      ([0, 0, 100, 200], [0, 50, 100, 150]),
                      ([0, 0, 100, 200], [0, 0, 40, 100]),
                      ([0, 0, 100, 200], [40, 0, 60, 80])):
            rows = [body(box) for box in boxes]
            self.assertEqual(consolidate_people(rows, counter), rows)
        counter.assert_not_called()

    def test_callback_failure_preserves_candidates(self):
        rows = [body(LARGE), body(SMALL)]
        counter = Mock(side_effect=RuntimeError("unavailable"))
        self.assertEqual(consolidate_people(rows, counter), rows)

    def test_count_receives_union_once_for_same_group_roi(self):
        counter = Mock(return_value=1)
        rows = [body([0, 0, 200, 400]), body([20, 1, 180, 200]), body([20, 2, 180, 202])]
        result = consolidate_people(rows, counter)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["duplicate_boxes"], 2)
        counter.assert_called_once_with([0., 0., 200., 400.])

    def test_bounded_candidates_leave_overflow_intact(self):
        rows = [body([i * 100, 0, i * 100 + 40, 100]) for i in range(8)]
        rows.extend([body(LARGE), body(SMALL)])
        counter = Mock(return_value=1)
        self.assertEqual(consolidate_people(rows, counter), rows)
        counter.assert_not_called()

    def test_empty_and_malformed_boxes_remain_for_callers_validation(self):
        self.assertEqual(consolidate_people([]), [])
        for box in (None, [1, 2], [1, 2, 0, 3], [0, 0, float("inf"), 3]):
            rows = [{"bbox": box}, body(SMALL)]
            self.assertEqual(len(consolidate_people(rows, lambda _: 1)), 2)


if __name__ == "__main__":
    unittest.main()
