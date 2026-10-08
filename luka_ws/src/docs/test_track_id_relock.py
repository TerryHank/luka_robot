import math
import unittest


def continuous(old_xyz, new_xyz, dt, max_gap=1.5, max_position=0.8, max_depth=0.6):
    delta = math.sqrt(sum((b - a) ** 2 for a, b in zip(old_xyz, new_xyz)))
    depth_delta = abs(new_xyz[2] - old_xyz[2])
    return dt <= max_gap and delta <= max_position and depth_delta <= max_depth


class TrackIdRelockTests(unittest.TestCase):
    def test_single_person_id_chain_relocks(self):
        xyz = (0.0, 0.0, 2.0)
        for new_id, new_xyz in ((33, (0.1, 0.0, 2.1)), (39, (0.2, 0.0, 2.2))):
            self.assertTrue(continuous(xyz, new_xyz, 0.3))
            xyz = new_xyz

    def test_large_depth_jump_rejected(self):
        self.assertFalse(continuous((0.0, 0.0, 2.0), (0.0, 0.0, 5.0), 0.3))

    def test_late_candidate_rejected(self):
        self.assertFalse(continuous((0.0, 0.0, 2.0), (0.1, 0.0, 2.1), 1.6))


if __name__ == '__main__':
    unittest.main()
