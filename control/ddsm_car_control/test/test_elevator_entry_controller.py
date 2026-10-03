import math

import numpy as np

from sensor_msgs.msg import LaserScan

from ddsm_car_control.elevator_entry_controller import (
    ElevatorSafety,
    count_cabin_floor_points,
    corridor_is_clear,
    detect_depth_opening,
    lidar_door_is_open,
    nav2_path_is_valid,
    normalize_angle,
)

from action_msgs.msg import GoalStatus


def make_scan(obstacles):
    scan = LaserScan()
    scan.angle_min = -math.pi
    scan.angle_increment = math.pi / 180.0
    scan.range_min = 0.05
    scan.range_max = 10.0
    scan.ranges = [float("inf")] * 360
    for angle_deg, distance in obstacles:
        index = int(round((math.radians(angle_deg) - scan.angle_min) / scan.angle_increment))
        scan.ranges[index] = distance
    return scan


def test_elevator_safety_requires_all_conditions():
    safe = ElevatorSafety(True, "open", True, "stopped")
    assert safe.safe_to_enter
    assert not ElevatorSafety(False, "open", True, "stopped").safe_to_enter
    assert not ElevatorSafety(True, "closed", True, "stopped").safe_to_enter
    assert not ElevatorSafety(True, "open", False, "stopped").safe_to_enter
    assert not ElevatorSafety(True, "open", True, "moving").safe_to_enter


def test_corridor_rejects_front_obstacle_inside_robot_width():
    scan = make_scan([(0.0, 0.50)])
    assert not corridor_is_clear(scan, clearance_distance=0.75, half_width=0.27)


def test_corridor_accepts_side_and_far_obstacles():
    scan = make_scan([(45.0, 0.50), (0.0, 1.20)])
    assert corridor_is_clear(scan, clearance_distance=0.75, half_width=0.27)


def test_corridor_ignores_one_isolated_depth_point_when_cluster_required():
    scan = make_scan([(14.0, 0.75)])
    assert corridor_is_clear(
        scan,
        clearance_distance=0.75,
        half_width=0.27,
        min_blocking_points=2,
    )


def test_corridor_rejects_two_adjacent_blocking_points():
    scan = make_scan([(0.0, 0.50), (1.0, 0.50)])
    assert not corridor_is_clear(
        scan,
        clearance_distance=0.75,
        half_width=0.27,
        min_blocking_points=2,
    )


def test_lidar_door_rejects_closed_panel_and_accepts_opening():
    closed = make_scan([(angle, 1.20) for angle in range(-12, 13)])
    opened = make_scan([(angle, 1.00) for angle in range(-3, 3)])
    settings = {
        "check_distance": 1.50,
        "half_width": 0.27,
        "min_blocking_points": 20,
    }

    assert not lidar_door_is_open(closed, **settings)
    assert lidar_door_is_open(opened, **settings)


def test_normalize_angle_wraps():
    assert math.isclose(normalize_angle(3.0 * math.pi), math.pi, abs_tol=1e-9)


def test_nav2_path_requires_success_and_nonempty_path():
    assert nav2_path_is_valid(GoalStatus.STATUS_SUCCEEDED, 2)
    assert not nav2_path_is_valid(GoalStatus.STATUS_SUCCEEDED, 0)
    assert not nav2_path_is_valid(GoalStatus.STATUS_ABORTED, 2)


def test_cabin_floor_points_detect_synthetic_floor_strip():
    height = 240
    width = 320
    fy = 288.68301392
    cy = 120.27767944
    depth = np.zeros((height, width), dtype=np.float32)
    for row in range(189, 205):
        floor_depth = 0.32 * fy / (row - cy)
        depth[row, 125:196] = floor_depth

    count = count_cabin_floor_points(
        depth,
        fx=288.68301392,
        fy=fy,
        cx=160.12034607,
        cy=cy,
        camera_forward_offset=0.20,
        camera_height=0.32,
        min_x=1.30,
        max_x=1.55,
        half_width=0.22,
        z_tolerance=0.07,
    )

    assert count > 80


def test_cabin_floor_points_reject_closed_door_plane():
    depth = np.full((240, 320), 0.70, dtype=np.float32)
    count = count_cabin_floor_points(
        depth,
        fx=288.68301392,
        fy=288.68301392,
        cx=160.12034607,
        cy=120.27767944,
        camera_forward_offset=0.20,
        camera_height=0.32,
        min_x=1.30,
        max_x=1.55,
        half_width=0.22,
        z_tolerance=0.07,
    )

    assert count == 0


def test_depth_opening_accepts_far_center_and_rejects_near_door():
    far = np.full((240, 320), 6.0, dtype=np.float32)
    near = np.full((240, 320), 0.8, dtype=np.float32)
    settings = {
        "cx": 160.0,
        "center_half_fraction": 0.18,
        "top_fraction": 0.15,
        "bottom_fraction": 0.94,
        "min_depth": 2.0,
        "min_valid_points": 500,
    }

    far_open, far_points, far_median = detect_depth_opening(far, **settings)
    near_open, near_points, near_median = detect_depth_opening(near, **settings)

    assert far_open is True
    assert far_points >= 500
    assert far_median == 6.0
    assert near_open is False
    assert near_points >= 500
    assert math.isclose(near_median, 0.8, abs_tol=1e-6)
