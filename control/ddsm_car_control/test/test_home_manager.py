import math
from pathlib import Path

import pytest
import yaml

from ddsm_car_control.ddsm_home_manager import (
    HomePose,
    compute_map_identity,
    dump_home_pose,
    load_home_pose,
    make_navigate_goal,
    map_identity_matches,
    yaw_from_quaternion,
)


def write_test_map(tmp_path: Path) -> Path:
    image = tmp_path / "map.pgm"
    image.write_bytes(b"P5\n2 2\n255\n\x00\xff\xcd\xff")
    map_file = tmp_path / "map.yaml"
    map_file.write_text(
        "\n".join(
            [
                "image: map.pgm",
                "mode: trinary",
                "resolution: 0.050",
                "origin: [0.0, 0.0, 0.0]",
                "negate: 0",
                "occupied_thresh: 0.65",
                "free_thresh: 0.196",
            ]
        ),
        encoding="utf-8",
    )
    return map_file


def test_dump_and_load_home_pose_round_trip_with_map_identity(tmp_path):
    map_file = write_test_map(tmp_path)
    home_file = tmp_path / "home_pose.yaml"
    pose = HomePose(
        configured=True,
        frame_id="map",
        x=1.25,
        y=-0.5,
        yaw=1.57,
        map_file=str(map_file),
        map_sha256=compute_map_identity(map_file),
    )

    dump_home_pose(home_file, pose)
    loaded = load_home_pose(home_file)

    assert loaded.configured is True
    assert loaded.frame_id == "map"
    assert loaded.x == 1.25
    assert loaded.y == -0.5
    assert loaded.yaw == pytest.approx(1.57, abs=1e-6)
    assert loaded.map_file == str(map_file)
    assert loaded.map_sha256 == compute_map_identity(map_file)


def test_map_identity_rejects_stale_home_after_map_file_changes(tmp_path):
    map_file = write_test_map(tmp_path)
    pose = HomePose(
        configured=True,
        frame_id="map",
        x=0.0,
        y=0.0,
        yaw=0.0,
        map_file=str(map_file),
        map_sha256=compute_map_identity(map_file),
    )

    assert map_identity_matches(pose, map_file) is True

    (tmp_path / "map.pgm").write_bytes(b"P5\n2 2\n255\n\x00\x00\x00\x00")

    assert map_identity_matches(pose, map_file) is False


def test_make_navigate_goal_uses_map_pose_and_yaw():
    pose = HomePose(
        configured=True,
        frame_id="map",
        x=2.0,
        y=3.0,
        yaw=math.pi / 2.0,
    )

    goal = make_navigate_goal(pose)

    assert goal.pose.header.frame_id == "map"
    assert goal.pose.pose.position.x == 2.0
    assert goal.pose.pose.position.y == 3.0
    assert yaw_from_quaternion(goal.pose.pose.orientation) == pytest_approx_angle(
        math.pi / 2.0
    )


def pytest_approx_angle(value):
    return pytest.approx(value, abs=1e-6)


def test_default_home_template_is_loaded_as_unconfigured(tmp_path):
    home_file = tmp_path / "home_pose.yaml"
    home_file.write_text(
        yaml.safe_dump(
            {
                "configured": False,
                "frame_id": "map",
                "x": 0.0,
                "y": 0.0,
                "yaw": 0.0,
                "map_file": "",
                "map_sha256": "",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    loaded = load_home_pose(home_file)

    assert loaded.configured is False
