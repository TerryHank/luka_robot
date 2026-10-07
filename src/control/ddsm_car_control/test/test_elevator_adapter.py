import json

import pytest

from ddsm_car_control.ddsm_elevator_adapter import (
    ElevatorStatus,
    parse_manual_status,
    status_json,
)


def test_manual_status_updates_only_supplied_fields():
    previous = ElevatorStatus(
        available=True,
        door="closed",
        floor_id="floor_1",
        car_present=True,
        motion="stopped",
    )
    status = parse_manual_status('{"door": "open"}', previous)

    assert status.available is True
    assert status.door == "open"
    assert status.floor_id == "floor_1"
    assert status.car_present is True
    assert status.motion == "stopped"
    assert json.loads(status_json(status))["backend"] == "manual"


def test_manual_status_rejects_unknown_state_values():
    with pytest.raises(ValueError, match="invalid elevator door state"):
        parse_manual_status('{"door": "blocked"}', ElevatorStatus())
