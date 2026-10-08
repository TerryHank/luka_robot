import math
from pathlib import Path

from geometry_msgs.msg import PoseStamped

from ddsm_car_control.final_approach_navigator import (
    PlanarPose,
    compute_front_clearance,
    compute_servo_command,
    compute_staging_pose,
    fit_dominant_scan_line,
    yaw_to_quaternion,
)


PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def make_pose(x: float, y: float, yaw: float) -> PoseStamped:
    pose = PoseStamped()
    pose.header.frame_id = "map"
    pose.pose.position.x = x
    pose.pose.position.y = y
    pose.pose.orientation = yaw_to_quaternion(yaw)
    return pose


def test_compute_staging_pose_offsets_behind_goal_heading():
    goal = make_pose(1.0, 2.0, 0.0)

    staging = compute_staging_pose(goal, 0.75)

    assert staging.header.frame_id == "map"
    assert math.isclose(staging.pose.position.x, 0.25)
    assert math.isclose(staging.pose.position.y, 2.0)


def test_compute_staging_pose_preserves_goal_yaw():
    goal = make_pose(1.0, 2.0, math.pi / 2.0)

    staging = compute_staging_pose(goal, 0.75)

    assert math.isclose(staging.pose.position.x, 1.0)
    assert math.isclose(staging.pose.position.y, 1.25)
    assert staging.pose.orientation.z == goal.pose.orientation.z
    assert staging.pose.orientation.w == goal.pose.orientation.w


def test_servo_command_stops_inside_final_tolerance():
    robot = PlanarPose(x=1.0, y=2.0, yaw=0.02)
    goal = PlanarPose(x=1.04, y=2.03, yaw=0.0)

    command = compute_servo_command(
        robot,
        goal,
        xy_tolerance=0.08,
        yaw_tolerance=0.18,
        max_linear_speed=0.10,
        max_angular_speed=0.45,
    )

    assert command.reached is True
    assert command.linear_x == 0.0
    assert command.angular_z == 0.0


def test_servo_command_drives_slowly_toward_final_pose():
    robot = PlanarPose(x=0.0, y=0.0, yaw=0.0)
    goal = PlanarPose(x=0.5, y=0.1, yaw=0.0)

    command = compute_servo_command(
        robot,
        goal,
        xy_tolerance=0.08,
        yaw_tolerance=0.18,
        max_linear_speed=0.10,
        max_angular_speed=0.45,
    )

    assert command.reached is False
    assert 0.0 < command.linear_x <= 0.10
    assert 0.0 < command.linear_y <= 0.06
    assert command.angular_z == 0.0


def test_servo_command_can_align_yaw_without_position_motion():
    robot = PlanarPose(x=0.0, y=0.0, yaw=0.0)
    goal = PlanarPose(x=0.4, y=0.2, yaw=0.5)

    command = compute_servo_command(
        robot,
        goal,
        xy_tolerance=0.08,
        yaw_tolerance=0.18,
        max_linear_speed=0.10,
        max_angular_speed=0.45,
        allow_position_motion=False,
    )

    assert command.reached is False
    assert command.linear_x == 0.0
    assert command.linear_y == 0.0
    assert 0.0 < command.angular_z <= 0.45


def test_front_clearance_uses_only_front_sector():
    ranges = [1.2, 0.4, 0.8, 2.0, 0.2]
    angle_min = -1.0
    angle_increment = 0.5

    clearance = compute_front_clearance(
        ranges,
        angle_min,
        angle_increment,
        front_half_angle=0.3,
    )

    assert clearance == 0.8


def test_fit_dominant_scan_line_detects_front_wall_direction():
    angle_min = -math.radians(30.0)
    angle_increment = math.radians(2.0)
    ranges = []
    for index in range(31):
        angle = angle_min + index * angle_increment
        ranges.append(1.0 / math.cos(angle))

    line = fit_dominant_scan_line(
        ranges,
        angle_min,
        angle_increment,
        max_range=3.0,
        front_half_angle=math.radians(35.0),
        min_points=10,
    )

    assert line is not None
    assert line.point_count == 31
    assert abs(abs(line.yaw) - math.pi / 2.0) < 0.1


def test_setup_installs_final_approach_console_script():
    setup_text = (PACKAGE_ROOT / "setup.py").read_text(encoding="utf-8")

    assert (
        "ddsm_final_approach_navigator = "
        "ddsm_car_control.final_approach_navigator:main"
    ) in setup_text


def test_bringup_launch_can_enable_final_approach_for_navigation_modes():
    launch_text = (
        PACKAGE_ROOT / "launch" / "ddsm_bringup.launch.py"
    ).read_text(encoding="utf-8")

    assert '"enable_final_approach"' in launch_text
    assert "executable=\"ddsm_final_approach_navigator\"" in launch_text
    assert (
        'condition=enabled_for_mode("enable_final_approach", ["nav", "auto_nav", "slam_nav"])'
        in launch_text
    )
