from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
LAUNCH = ROOT / "control/luka_person_following/launch/selected_follow.launch.py"


class FollowSafetyContractTest(unittest.TestCase):
    def test_real_direct_follow_velocity_enters_luka_safety_chain(self):
        text = LAUNCH.read_text(encoding="utf-8")
        self.assertIn("else '/nx/nav_smoothed'", text)
        self.assertNotIn("else '/cmd_vel'", text)

    def test_dry_run_keeps_fake_endpoints(self):
        text = LAUNCH.read_text(encoding="utf-8")
        self.assertIn("/luka_follow_dryrun/navigate_to_pose", text)
        self.assertIn("/luka_follow_dryrun/cmd_vel", text)
        self.assertIn("default_value='true'", text)

    def test_selected_default_does_not_idle_search(self):
        text = LAUNCH.read_text(encoding="utf-8")
        self.assertIn("'idle_search_total_timeout_sec': 0.0", text)
        self.assertIn("default_value='selected'", text)


if __name__ == "__main__":
    unittest.main()
