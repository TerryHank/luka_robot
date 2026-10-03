import json
import math
from pathlib import Path

import pytest

from ddsm_car_control.ddsm_multifloor_manager import (
    FloorMissionState,
    dump_floor_state,
    load_building_config,
    load_floor_state,
    make_initialpose_msg,
    make_elevator_command,
    make_status_json,
    parse_elevator_status,
    plan_floor_mission,
    resolve_destination_key,
)


def write_config(path: Path) -> None:
    path.write_text(
        """
building_id: hotel_a
current_floor_id: F1
default_elevator_id: elevator_A
floors:
  F1:
    map: /maps/floor_1.yaml
    semantic_map: /semantic/floor_1.yaml
    elevator_poses:
      elevator_A:
        entry_destination_id: f1_elevator_A_entry
        exit_initial_pose: {x: 1.0, y: 2.0, yaw: 1.57}
  F2:
    map: /maps/floor_2.yaml
    semantic_map: /semantic/floor_2.yaml
    elevator_poses:
      elevator_A:
        entry_destination_id: f2_elevator_A_entry
        exit_initial_pose: {x: 3.0, y: 4.0, yaw: 3.14}
destinations:
  room_203:
    floor_id: F2
    destination_id: f2_room_203
    display_name: 房间203
  door:
    floor_id: F1
    destination_id: wp_003
    display_name: 门口
""",
        encoding="utf-8",
    )


def test_load_building_config_resolves_destination_floor(tmp_path):
    config = tmp_path / "multifloor.yaml"
    write_config(config)

    building = load_building_config(config)
    mission = plan_floor_mission(building, "room_203")

    assert mission.current_floor_id == "F1"
    assert mission.target_floor_id == "F2"
    assert mission.elevator_entry_destination_id == "f1_elevator_A_entry"
    assert mission.final_destination_id == "f2_room_203"
    assert mission.target_map == "/maps/floor_2.yaml"
    assert mission.is_cross_floor is True


def test_resolve_destination_accepts_display_name_and_backend_id(tmp_path):
    config = tmp_path / "multifloor.yaml"
    write_config(config)
    building = load_building_config(config)

    assert resolve_destination_key(building, "门口") == "door"
    assert resolve_destination_key(building, "wp_003") == "door"
    assert plan_floor_mission(building, "门口").is_cross_floor is False


def test_unknown_destination_reports_clear_error(tmp_path):
    config = tmp_path / "multifloor.yaml"
    write_config(config)
    building = load_building_config(config)

    with pytest.raises(KeyError, match="unknown destination"):
        plan_floor_mission(building, "missing_room")


def test_floor_state_round_trip_and_status_json(tmp_path):
    state_file = tmp_path / "state.yaml"
    state = FloorMissionState(
        state="switching_map",
        requested_destination_id="room_203",
        current_floor_id="F1",
        target_floor_id="F2",
        elevator_id="elevator_A",
        final_destination_id="f2_room_203",
        target_map="/maps/floor_2.yaml",
        instruction="正在切换地图",
        updated_at=123.0,
    )

    dump_floor_state(state_file, state)
    loaded = load_floor_state(state_file)
    status = json.loads(make_status_json(loaded))

    assert loaded.state == "switching_map"
    assert loaded.final_destination_id == "f2_room_203"
    assert status["instruction"] == "正在切换地图"
    assert status["target_map"] == "/maps/floor_2.yaml"


def test_make_initialpose_msg_uses_map_frame_and_yaw():
    config = Path("/unused")
    _ = config
    msg = make_initialpose_msg(
        pose=type("Pose", (), {"x": 1.2, "y": -0.5, "yaw": math.pi / 2})(),
        frame_id="map",
    )

    assert msg.header.frame_id == "map"
    assert msg.pose.pose.position.x == pytest.approx(1.2)
    assert msg.pose.pose.position.y == pytest.approx(-0.5)
    assert msg.pose.pose.orientation.z == pytest.approx(math.sin(math.pi / 4))
    assert msg.pose.pose.orientation.w == pytest.approx(math.cos(math.pi / 4))
    assert msg.pose.covariance[0] > 0.0
    assert msg.pose.covariance[35] > 0.0


def test_parse_elevator_status_and_command_json():
    status = parse_elevator_status(
        '{"available": true, "door": "open", "floor_id": "F2", '
        '"car_present": true, "motion": "stopped"}'
    )
    assert status.available is True
    assert status.door == "open"
    assert status.floor_id == "F2"
    assert status.car_present is True
    assert status.motion == "stopped"

    command = json.loads(make_elevator_command("go_to_floor", "elevator_A", "F2"))
    assert command == {
        "command": "go_to_floor",
        "elevator_id": "elevator_A",
        "floor_id": "F2",
    }
