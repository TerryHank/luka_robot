from pathlib import Path

import pytest

from nav_llm_agent.capability_registry import CapabilityRegistry


CONFIG = Path(__file__).parents[1] / "config" / "capabilities.yaml"


def test_registry_loads_public_robot_capabilities():
    registry = CapabilityRegistry(str(CONFIG))
    names = {item.name for item in registry.exposed()}
    assert "navigate" in names
    assert "patrol_start" in names
    assert "elevator_enter" in names
    assert "elevator_resume" in names
    assert "elevator_command" not in names


def test_registry_validates_defaults_and_enums():
    registry = CapabilityRegistry(str(CONFIG))
    assert registry.validate_call("patrol_start", {}) == {"mode": "loop"}
    with pytest.raises(ValueError):
        registry.validate_call("patrol_start", {"mode": "forever"})


def test_registry_requires_elevator_floor():
    registry = CapabilityRegistry(str(CONFIG))
    with pytest.raises(ValueError):
        registry.validate_call("elevator_enter", {})


def test_cross_floor_navigation_accepts_optional_destination():
    registry = CapabilityRegistry(str(CONFIG))
    assert registry.validate_call("elevator_enter", {"floor": "floor_2"}) == {
        "floor": "floor_2",
        "destination": "",
    }
    assert registry.validate_call(
        "elevator_enter", {"floor": "floor_2", "destination": "kitchen"}
    ) == {"floor": "floor_2", "destination": "kitchen"}


def test_elevator_exit_uses_two_nav2_segments_before_switching_map():
    registry = CapabilityRegistry(str(CONFIG))
    steps = registry.workflows["elevator_exit_resume"]["steps"]
    assert [step["handler"] for step in steps] == [
        "navigate",
        "navigate",
        "switch_floor",
    ]
    assert steps[0]["arguments"]["waypoint"] == "elevator_exit_stage"
    assert steps[1]["arguments"]["waypoint"] == "wp_006"
