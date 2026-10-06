from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "system/xiaozhi"))

from luka_assistant_client import LukaAssistantClient


class FakeClient(LukaAssistantClient):
    def __init__(self, allow_motion=False):
        super().__init__(
            base_url="http://example.invalid",
            allow_motion=allow_motion,
            timeout=0.1,
        )
        self.posts = []

    def _json(self, path, body=None):
        if path == "/api/assistant/tools":
            return {
                "tools": {
                    "robot_status": "status",
                    "navigate": "navigate",
                    "cancel_all": "cancel",
                    "follow_start": "follow",
                    "follow_stop": "stop follow",
                },
                "generation": 42,
            }
        if path == "/api/assistant/execute":
            self.posts.append(body)
            return {"ok": True, "message": "ok"}
        raise AssertionError(path)


class XiaozhiClientPolicyTest(unittest.TestCase):
    def test_motion_is_disabled_by_default(self):
        client = FakeClient(False)
        with self.assertRaises(PermissionError):
            client.execute("navigate", {"name": "卧室"}, "带我去卧室")

    def test_stop_is_always_available(self):
        client = FakeClient(False)
        result = client.execute("cancel_all", {}, "停止")
        self.assertTrue(result["success"])
        self.assertEqual(client.posts[-1]["generation"], 42)

    def test_enabled_motion_carries_fresh_generation(self):
        client = FakeClient(True)
        client.execute("navigate", {"name": "卧室"}, "带我去卧室")
        body = client.posts[-1]
        self.assertEqual(body["generation"], 42)
        self.assertEqual(body["source"], "带我去卧室")

    def test_unknown_tool_is_rejected_locally(self):
        client = FakeClient(True)
        with self.assertRaises(ValueError):
            client.execute("shell", {}, "执行命令")


if __name__ == "__main__":
    unittest.main()
