import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2] / "control/luka_person_following"
sys.path.insert(0, str(ROOT))
from luka_person_following.tracking_mode import (
    normalize_tracking_mode, selection_policy)


class MotModePolicyTest(unittest.TestCase):
    def test_selected_mode_keeps_luka_id(self):
        ident, auto = selection_policy("selected", 12, False)
        self.assertEqual(ident, 12)
        self.assertFalse(auto)

    def test_automatic_mode_ignores_luka_tracker_id(self):
        ident, auto = selection_policy("automatic", 12, False)
        self.assertIsNone(ident)
        self.assertTrue(auto)

    def test_invalid_mode_rejected(self):
        with self.assertRaises(ValueError):
            normalize_tracking_mode("hybrid")


if __name__ == "__main__":
    unittest.main()
