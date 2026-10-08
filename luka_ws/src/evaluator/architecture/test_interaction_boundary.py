from .source_checks import ROOT, executable_text, sources


FORBIDDEN = ("geometry_msgs", "Twist(", "NavigateToPose", "ddsm_car_control", "/cmd_vel")


def test_xiaozhi_only_uses_the_assistant_api():
    paths = list(sources(ROOT / "system/xiaozhi"))
    assert paths, "Xiaozhi interaction sources must remain present"
    for path in paths:
        text = executable_text(path.read_text(encoding="utf-8"))
        for token in FORBIDDEN:
            assert token not in text, f"{path.relative_to(ROOT)} bypasses the assistant API: {token}"
    client = (ROOT / "system/xiaozhi/luka_assistant_client.py").read_text(encoding="utf-8")
    assert '"/api/assistant/execute"' in client


def test_inspector_checks_code_but_not_architecture_prose():
    source = '"""Never call NavigateToPose or Twist()."""\nimport geometry_msgs as motion\n'
    text = executable_text(source)
    assert "NavigateToPose" not in text
    assert "geometry_msgs" in text
    assert "Twist(" in executable_text("motion.Twist()")
