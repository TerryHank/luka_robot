from .source_checks import ROOT, executable_text, sources


def test_patrol_and_future_mission_code_do_not_implement_motion():
    legacy = ROOT / "visualization/console/nx_patrol_mission.py"
    assert legacy.is_file(), "Keep the patrol compatibility entrypoint until migration is validated"
    paths = [legacy, *sources(ROOT / "mission")]
    for path in paths:
        text = executable_text(path.read_text(encoding="utf-8"))
        for token in ("ddsm_car_control", "serial", "RS485", "Twist(", "NavigateToPose"):
            assert token not in text, f"{path.relative_to(ROOT)} implements a lower-layer interface: {token}"


def test_patrol_preserves_injected_navigation_and_state_recovery():
    text = (ROOT / "visualization/console/nx_patrol_mission.py").read_text(encoding="utf-8")
    assert "class PatrolMission" in text
    assert "self.send=send" in text
    assert "self.stop_nav" in text
    assert "self.cancel" in text
