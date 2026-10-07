from pathlib import Path
import ast
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "system/nav_llm_agent"
sys.path.insert(0, str(PKG))

def load_pure_backends():
    """Execute the real pure implementations without the ROS-loaded __init__."""
    scope = {"__name__": "luka_pure_backend_test"}
    for filename in ("base.py", "fallback.py"):
        path = PKG / "nav_llm_agent/llm" / filename
        tree = ast.parse(path.read_text(encoding="utf-8"))
        tree.body = [node for node in tree.body
                     if not (isinstance(node, ast.ImportFrom) and node.level)]
        exec(compile(tree, str(path), "exec"), scope)
    return scope["LLMBackend"], scope["FallbackBackend"]


LLMBackend, FallbackBackend = load_pure_backends()


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
        for path in llm_dir.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            # Architecture prose may name a forbidden interface. Check actual
            # code, including topic strings, while excluding only docstrings.
            for node in ast.walk(tree):
                body = getattr(node, "body", None)
                if isinstance(body, list) and body and isinstance(body[0], ast.Expr):
                    value = body[0].value
                    if isinstance(value, ast.Constant) and isinstance(value.value, str):
                        del body[0]
            text = ast.unparse(tree)
            for forbidden in ("cmd_vel", "NavigateToPose", "ddsm_car_control"):
                with self.subTest(path=path.name, forbidden=forbidden):
                    self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
