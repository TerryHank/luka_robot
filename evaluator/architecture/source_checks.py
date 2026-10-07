"""Inspect executable Python syntax without importing robot modules."""
import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def sources(directory):
    """Canonical source only: compatibility links and historical copies are excluded."""
    for path in sorted(directory.rglob("*.py")):
        relative = path.relative_to(ROOT)
        if path.is_symlink() or any(
                part.startswith("backup-") or part in
                {"__pycache__", "legacy", "history", "fixtures", "artifacts", "test", "tests", "src"}
                for part in relative.parts[:-1]):
            continue
        if path.name.startswith("test_") or any(
                marker in path.name for marker in (".before", ".pre_", ".bak")):
            continue
        yield path


def tree(path):
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def executable_text(source):
    parsed = ast.parse(source)
    for node in ast.walk(parsed):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr):
            value = body[0].value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                del body[0]
    return ast.unparse(parsed)


def imported_modules(parsed):
    result = set()
    for node in ast.walk(parsed):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module)
    return result


def twist_publishers(parsed):
    names = {"Twist"}
    for node in ast.walk(parsed):
        if isinstance(node, ast.ImportFrom) and node.module == "geometry_msgs.msg":
            names.update(alias.asname or alias.name for alias in node.names if alias.name == "Twist")
    result = []
    for node in ast.walk(parsed):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "create_publisher"):
            continue
        keywords = {item.arg: item.value for item in node.keywords}
        message_type = node.args[0] if node.args else keywords.get("msg_type")
        topic = node.args[1] if len(node.args) > 1 else keywords.get("topic")
        if message_type is not None and ast.unparse(message_type).split(".")[-1] in names:
            assert topic is not None, "Twist publisher topic must be explicit"
            result.append(topic.value if isinstance(topic, ast.Constant) else ast.unparse(topic))
    return sorted(result)
