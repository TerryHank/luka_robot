from pathlib import Path

import yaml

from nav_llm_agent.floor_transfer import (
    load_floor_target,
    load_transfer_state,
    save_initial_pose_file,
    save_transfer_state,
    state_from_target,
)


def building_file(tmp_path: Path) -> Path:
    semantic_dir = tmp_path / "semantic" / "floor_2"
    semantic_dir.mkdir(parents=True)
    (semantic_dir / "map_manifest.yaml").write_text(
        yaml.safe_dump({"poi_database": "pois.yaml"}), encoding="utf-8"
    )
    (semantic_dir / "pois.yaml").write_text(
        yaml.safe_dump(
            {
                "pois": [
                    {"id": "wp_001", "x": 1.0, "y": 2.0, "yaw": 0.25},
                    {"id": "wp_003", "x": 3.0, "y": 4.0, "yaw": 0.5},
                ]
            }
        ),
        encoding="utf-8",
    )
    path = tmp_path / "building.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "default_elevator_id": "elevator_A",
                "floors": {
                    "floor_2": {
                        "map": "/maps/floor_2.yaml",
                        "semantic_map": str(semantic_dir / "map_manifest.yaml"),
                        "patrol_route": "/routes/floor_2.yaml",
                        "elevator_poses": {
                            "elevator_A": {
                                "exit_initial_pose": {
                                    "x": 1.0,
                                    "y": 2.0,
                                    "yaw": 0.25,
                                }
                            }
                        },
                    }
                },
                "destinations": {
                    "floor2_door": {
                        "floor_id": "floor_2",
                        "destination_id": "wp_001",
                        "display_name": "二层门口",
                    },
                    "kitchen": {
                        "floor_id": "floor_2",
                        "destination_id": "wp_003",
                        "display_name": "厨房",
                    },
                },
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    return path


def test_default_destination_is_floor_door(tmp_path):
    target = load_floor_target(str(building_file(tmp_path)), "floor_2")
    assert target.destination_key == "floor2_door"
    assert target.destination_id == "wp_001"
    assert target.semantic_manifest_file.endswith("semantic/floor_2/map_manifest.yaml")
    assert target.patrol_route_file == "/routes/floor_2.yaml"
    assert (target.target_x, target.target_y, target.target_yaw) == (1.0, 2.0, 0.25)


def test_named_destination_and_state_survive_restart(tmp_path):
    target = load_floor_target(
        str(building_file(tmp_path)), "floor_2", "kitchen"
    )
    state_file = tmp_path / "state.yaml"
    state = state_from_target(target, "switching_map")
    save_transfer_state(str(state_file), state)
    assert load_transfer_state(str(state_file)) == state
    assert state.destination_id == "wp_003"
    assert (state.target_x, state.target_y, state.target_yaw) == (3.0, 4.0, 0.5)


def test_transfer_pose_file_uses_elevator_exit_pose(tmp_path):
    target = load_floor_target(str(building_file(tmp_path)), "floor_2")
    pose_file = tmp_path / "pose.yaml"
    save_initial_pose_file(str(pose_file), target)
    pose = yaml.safe_load(pose_file.read_text(encoding="utf-8"))
    assert pose == {
        "configured": True,
        "x": 1.0,
        "y": 2.0,
        "yaw": 0.25,
        "map_file": "/maps/floor_2.yaml",
    }
