from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class P10SafetyGateStaticTest(unittest.TestCase):
    def test_real_follow_direct_velocity_enters_luka_chain(self):
        launch = (
            ROOT / "control/luka_person_following/launch/selected_follow.launch.py"
        ).read_text(encoding="utf-8")
        self.assertIn("/nx/nav_smoothed", launch)

    def test_base_consumes_only_nav_safe(self):
        config = (ROOT / "common/config/nx_manual_base.yaml").read_text(
            encoding="utf-8")
        self.assertIn("nav_cmd_vel_topic: /nx/nav_safe", config)

    def test_collision_monitor_sits_after_guard(self):
        nav = (ROOT / "common/config/nx_nav2.yaml").read_text(
            encoding="utf-8")
        self.assertIn("cmd_vel_in_topic: /nx/nav_guarded", nav)
        self.assertIn("cmd_vel_out_topic: /nx/nav_safe", nav)

    def test_p10_preflight_contains_no_motion_commands(self):
        text = (
            ROOT / "system/scripts/p10_preflight_readonly.sh"
        ).read_text(encoding="utf-8")
        forbidden = (
            "ros2 topic pub",
            "ros2 action send_goal",
            "ros2 service call /nx/navigation_enable",
            "ros2 service call /luka_person_following/set_enabled",
        )
        for value in forbidden:
            self.assertNotIn(value, text)

    def test_real_motion_is_not_default(self):
        launch = (
            ROOT / "control/luka_person_following/launch/selected_follow.launch.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "DeclareLaunchArgument('dry_run', default_value='true'",
            launch,
        )


if __name__ == "__main__":
    unittest.main()
