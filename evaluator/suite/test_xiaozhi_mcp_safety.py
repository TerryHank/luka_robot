from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
CONSOLE = ROOT / "visualization/console"
sys.path.insert(0, str(CONSOLE))

import nx_assistant_tools as tools


class XiaozhiStaticSafetyTest(unittest.TestCase):
    def test_mcp_server_has_no_direct_motion_interfaces(self):
        text = (ROOT / "system/xiaozhi/luka_mcp_server.py").read_text(
            encoding="utf-8")
        forbidden = (
            "geometry_msgs",
            "Twist(",
            "NavigateToPose",
            "ddsm_car_control",
            "/cmd_vel",
            "/nx/follow_safe",
        )
        for token in forbidden:
            self.assertNotIn(token, text)

    def test_config_does_not_override_motion_gate(self):
        text = (ROOT / "system/xiaozhi/mcp_config.luka.json").read_text(
            encoding="utf-8")
        self.assertNotIn("LUKA_XIAOZHI_ALLOW_MOTION", text)

    def test_server_uses_explicit_stdio_transport(self):
        text = (ROOT / "system/xiaozhi/luka_mcp_server.py").read_text(
            encoding="utf-8")
        self.assertIn('mcp.run(transport="stdio")', text)

    def test_follow_commands_are_grounded(self):
        tools.validate("follow_start", {}, "跟着我")
        tools.validate("follow_stop", {}, "停止跟随")
        with self.assertRaises(ValueError):
            tools.validate("follow_start", {}, "你会跟随吗")

    def test_follow_direct_commands(self):
        self.assertEqual(tools.direct("跟着我")["tool"], "follow_start")
        self.assertEqual(tools.direct("停止跟随")["tool"], "follow_stop")


if __name__ == "__main__":
    unittest.main()
