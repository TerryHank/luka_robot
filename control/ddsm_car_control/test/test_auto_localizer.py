import math
from pathlib import Path

from rclpy.qos import QoSDurabilityPolicy, QoSReliabilityPolicy
from nav_msgs.msg import OccupancyGrid
from sensor_msgs.msg import LaserScan

from ddsm_car_control.ddsm_auto_localizer import (
    SavedLocalizationPose,
    choose_escape_twist_from_scan,
    covariance_is_converged,
    dump_saved_pose,
    load_saved_pose,
    make_initial_pose,
    make_initial_pose_qos,
    map_identity_matches,
    scan_to_map_match_score,
    scan_has_rotation_clearance,
    use_latest_tf_for_initial_pose,
    warm_start_should_timeout,
)


def write_test_map(tmp_path: Path, image_bytes: bytes = b"pgm") -> Path:
    image_path = tmp_path / "map.pgm"
    image_path.write_bytes(image_bytes)
    map_path = tmp_path / "map.yaml"
    map_path.write_text(
        "image: map.pgm\nresolution: 0.05\norigin: [0.0, 0.0, 0.0]\n",
        encoding="utf-8",
    )
    return map_path


def test_saved_pose_round_trip_is_tied_to_current_map(tmp_path):
    map_path = write_test_map(tmp_path)
    pose_path = tmp_path / "last_pose.yaml"
    saved = SavedLocalizationPose(
        configured=True,
        frame_id="map",
        x=1.2,
        y=-0.4,
        yaw=0.7,
        map_file=str(map_path),
        map_sha256="",
    )

    dump_saved_pose(pose_path, saved, map_path)
    loaded = load_saved_pose(pose_path)

    assert loaded.configured is True
    assert loaded.frame_id == "map"
    assert math.isclose(loaded.x, 1.2)
    assert math.isclose(loaded.y, -0.4)
    assert math.isclose(loaded.yaw, 0.7)
    assert map_identity_matches(loaded, map_path)

    write_test_map(tmp_path, image_bytes=b"changed")

    assert not map_identity_matches(loaded, map_path)


def test_make_initial_pose_preserves_pose_and_sets_realistic_covariance():
    saved = SavedLocalizationPose(
        configured=True,
        frame_id="map",
        x=2.5,
        y=1.25,
        yaw=math.pi / 2.0,
        map_file="",
        map_sha256="",
    )

    msg = make_initial_pose(saved, xy_std=0.25, yaw_std=0.35)

    assert msg.header.frame_id == "map"
    assert math.isclose(msg.pose.pose.position.x, 2.5)
    assert math.isclose(msg.pose.pose.position.y, 1.25)
    assert math.isclose(msg.pose.covariance[0], 0.25 * 0.25)
    assert math.isclose(msg.pose.covariance[7], 0.25 * 0.25)
    assert math.isclose(msg.pose.covariance[35], 0.35 * 0.35)


def test_initial_pose_qos_matches_amcl_subscription_durability():
    qos = make_initial_pose_qos()

    assert qos.durability == QoSDurabilityPolicy.TRANSIENT_LOCAL
    assert qos.reliability == QoSReliabilityPolicy.RELIABLE


def test_initial_pose_uses_latest_tf_lookup_to_avoid_future_extrapolation():
    saved = SavedLocalizationPose(
        configured=True,
        frame_id="map",
        x=0.0,
        y=0.0,
        yaw=0.0,
        map_file="",
        map_sha256="",
    )
    msg = make_initial_pose(saved, xy_std=0.25, yaw_std=0.35)
    msg.header.stamp.sec = 123
    msg.header.stamp.nanosec = 456

    prepared = use_latest_tf_for_initial_pose(msg)

    assert prepared.header.stamp.sec == 0
    assert prepared.header.stamp.nanosec == 0


def test_covariance_convergence_requires_xy_and_yaw_below_threshold():
    covariance = [0.0] * 36
    covariance[0] = 0.08 * 0.08
    covariance[7] = 0.09 * 0.09
    covariance[35] = 0.12 * 0.12

    assert covariance_is_converged(covariance, xy_std_threshold=0.10, yaw_std_threshold=0.20)

    covariance[35] = 0.35 * 0.35

    assert not covariance_is_converged(
        covariance, xy_std_threshold=0.10, yaw_std_threshold=0.20
    )


def make_test_occupancy_grid() -> OccupancyGrid:
    grid = OccupancyGrid()
    grid.info.resolution = 1.0
    grid.info.width = 8
    grid.info.height = 8
    grid.info.origin.orientation.w = 1.0
    grid.data = [0] * (grid.info.width * grid.info.height)
    for y in range(grid.info.height):
        grid.data[y * grid.info.width + 5] = 100
    return grid


def make_wall_scan() -> LaserScan:
    scan = LaserScan()
    scan.range_min = 0.05
    scan.range_max = 20.0
    scan.angle_min = -math.pi / 4.0
    scan.angle_increment = math.pi / 4.0
    scan.ranges = [
        math.sqrt(8.0),
        2.0,
        math.sqrt(8.0),
    ]
    return scan


def test_scan_to_map_match_accepts_aligned_pose_and_rejects_shifted_pose():
    grid = make_test_occupancy_grid()
    scan = make_wall_scan()

    aligned_score, aligned_points = scan_to_map_match_score(
        grid,
        scan,
        base_x=3.0,
        base_y=3.0,
        base_yaw=0.0,
        laser_x=0.0,
        laser_y=0.0,
        laser_yaw=0.0,
        hit_distance=0.1,
        max_points=10,
        min_points=3,
    )
    shifted_score, shifted_points = scan_to_map_match_score(
        grid,
        scan,
        base_x=1.0,
        base_y=3.0,
        base_yaw=0.0,
        laser_x=0.0,
        laser_y=0.0,
        laser_yaw=0.0,
        hit_distance=0.1,
        max_points=10,
        min_points=3,
    )

    assert aligned_points == 3
    assert math.isclose(aligned_score, 1.0)
    assert shifted_points == 3
    assert math.isclose(shifted_score, 0.0)


def test_scan_clearance_blocks_rotation_near_obstacles():
    scan = LaserScan()
    scan.range_min = 0.05
    scan.range_max = 12.0
    scan.ranges = [float("inf"), 1.5, 0.7, 2.0]

    assert scan_has_rotation_clearance(scan, min_clearance=0.45)

    scan.ranges = [float("nan"), 0.32, 1.1]

    assert not scan_has_rotation_clearance(scan, min_clearance=0.45)


def test_warm_start_timeout_waits_until_amcl_pose_feedback_exists():
    assert not warm_start_should_timeout(
        amcl_pose_seen=False,
        elapsed_seconds=120.0,
        warm_start_timeout=20.0,
    )
    assert not warm_start_should_timeout(
        amcl_pose_seen=True,
        elapsed_seconds=10.0,
        warm_start_timeout=20.0,
    )
    assert warm_start_should_timeout(
        amcl_pose_seen=True,
        elapsed_seconds=20.1,
        warm_start_timeout=20.0,
    )


def make_sector_scan(*, left: float, right: float, back: float, front: float) -> LaserScan:
    scan = LaserScan()
    scan.range_min = 0.05
    scan.range_max = 12.0
    scan.angle_min = -math.pi
    scan.angle_max = math.pi
    scan.angle_increment = math.pi / 4.0
    scan.ranges = [
        back,
        right,
        right,
        front,
        front,
        left,
        left,
        back,
        back,
    ]
    return scan


def test_rotation_escape_prefers_more_open_lateral_side():
    scan = make_sector_scan(left=1.2, right=0.35, back=0.8, front=0.35)

    twist = choose_escape_twist_from_scan(scan, speed=0.08, min_clearance=0.45)

    assert twist is not None
    assert math.isclose(twist.linear.x, 0.0)
    assert math.isclose(twist.linear.y, 0.08)
    assert math.isclose(twist.angular.z, 0.0)


def test_rotation_escape_uses_back_when_lateral_sides_are_blocked():
    scan = make_sector_scan(left=0.30, right=0.35, back=0.9, front=0.35)

    twist = choose_escape_twist_from_scan(scan, speed=0.08, min_clearance=0.45)

    assert twist is not None
    assert math.isclose(twist.linear.x, -0.08)
    assert math.isclose(twist.linear.y, 0.0)
    assert math.isclose(twist.angular.z, 0.0)


def test_rotation_escape_refuses_motion_when_no_direction_is_clear():
    scan = make_sector_scan(left=0.30, right=0.35, back=0.4, front=0.35)

    assert choose_escape_twist_from_scan(scan, speed=0.08, min_clearance=0.45) is None
