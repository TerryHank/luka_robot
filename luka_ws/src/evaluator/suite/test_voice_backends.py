from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class VoiceBackendContractTest(unittest.TestCase):
    def test_legacy_is_default_and_backends_are_mutually_exclusive(self):
        text = (ROOT / "system/bringup/start_nx_voice.sh").read_text(encoding="utf-8")
        self.assertIn('LUKA_VOICE_BACKEND:-legacy', text)
        self.assertIn('VOICE_BACKEND" == "drobotics"', text)
        self.assertIn("start_rdk_voice_suite.sh", text)

    def test_drobotics_backend_uses_official_nodes(self):
        text = (ROOT / "system/bringup/start_rdk_voice_suite.sh").read_text(encoding="utf-8")
        self.assertIn("sensevoice_ros2", text)
        self.assertIn("hobot_tts", text)
        self.assertIn("voice_suite_bridge", text)
        self.assertNotIn("nx_voice_gateway.py", text)

    def test_bridge_is_wake_gated_and_has_no_motion_interface(self):
        text = (ROOT / "system/nav_llm_agent/nav_llm_agent/voice_suite_bridge.py").read_text(
            encoding="utf-8")
        self.assertIn("armed_until", text)
        self.assertIn("asr_ignored reason=not_woken", text)
        self.assertNotIn("NavigateToPose", text)
        self.assertNotIn("cmd_vel", text)
        self.assertNotIn("create_client(", text)


if __name__ == "__main__":
    unittest.main()
