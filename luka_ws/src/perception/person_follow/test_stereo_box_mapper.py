import unittest

from stereo_box_mapper import combine_full_and_zoom


class Mapper:
    def to_full(self, box):
        return box


def person(box, score):
    return dict(class_='person', bbox=list(box), confidence=score)


class DualViewDetectionTests(unittest.TestCase):
    def test_disjoint_people_from_different_views_both_remain(self):
        rows = combine_full_and_zoom(
            [person([10, 20, 100, 200], .8)],
            [person([300, 20, 390, 200], .7)], Mapper(), lambda _: 1)
        self.assertEqual(len(rows), 2)

    def test_duplicate_needs_unique_face_before_fusion(self):
        full = [person([10, 20, 100, 200], .4)]
        zoom = [person([12, 22, 98, 198], .9)]
        for count in (0, 2):
            self.assertEqual(len(combine_full_and_zoom(full, zoom, Mapper(), lambda _: count)), 2)
        rows = combine_full_and_zoom(full, zoom, Mapper(), lambda _: 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['confidence'], .9)
        self.assertEqual(rows[0]['bbox'], [10., 20., 100., 200.])


if __name__ == '__main__':
    unittest.main()
