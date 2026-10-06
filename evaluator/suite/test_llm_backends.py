from pathlib import Path
import ast
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "system/nav_llm_agent"
sys.path.insert(0, str(PKG))

from nav_llm_agent.llm.base import LLMBackend
from nav_llm_agent.llm.fallback import FallbackBackend


class DummyBackend(LLMBackend):
    def __init__(self, name, result=None, error=None):
        self.name=name
        self.result=result
        self.error=error

    def generate(self, messages, tools=None):
        del messages, tools
        if self.error:
            raise self.error
        return self.result


def load_pure_ros_helpers():
    path = PKG / "nav_llm_agent/llm/ros_topic_backend.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    keep = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name in ("format_prompt", "extract_result_text")
    ]
    scope = {}
    exec(compile(ast.Module(body=keep, type_ignores=[]), str(path), "exec"), scope)
    return scope


class LlmBackendTest(unittest.TestCase):
    def test_fallback_order(self):
        backend=FallbackBackend([
            DummyBackend("xlm", error=TimeoutError()),
            DummyBackend("llamacpp", result="ok"),
            DummyBackend("ollama", result="late"),
        ])
        self.assertEqual(backend.generate([{"role":"user","content":"hi"}]), "ok")
        self.assertEqual(backend.last_backend, "llamacpp")

    def test_all_fail_is_data_error_only(self):
        backend=FallbackBackend([
            DummyBackend("a", error=RuntimeError()),
            DummyBackend("b", error=TimeoutError()),
        ])
        with self.assertRaises(RuntimeError):
            backend.generate([{"role":"user","content":"hi"}])

    def test_prompt_format_preserves_roles(self):
        helper=load_pure_ros_helpers()["format_prompt"]
        text=helper([
            {"role":"system","content":"policy"},
            {"role":"user","content":"hello"},
        ])
        self.assertIn("[system] policy", text)
        self.assertIn("[user] hello", text)

    def test_backend_layer_has_no_motion_api(self):
        llm_dir=PKG / "nav_llm_agent/llm"
        text="\n".join(
            p.read_text(encoding="utf-8")
            for p in llm_dir.glob("*.py")
        )
        for forbidden in ("cmd_vel", "NavigateToPose", "ddsm_car_control"):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
