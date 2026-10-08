import math

from ddsm_car_control.laser_scan_deskewer import (
    Pose2D,
    deskew_ranges,
    interpolate_pose,
)


def test_interpolate_pose_wraps_yaw_over_pi_boundary():
    before = Pose2D(0.0, 0.0, 0.0, math.radians(179.0))
    after = Pose2D(1.0, 2.0, 4.0, math.radians(-179.0))

    result = interpolate_pose(before, after, 0.5)

    assert result.x == 1.0
    assert result.y == 2.0
    assert abs(abs(result.yaw) - math.pi) < 1e-6


def test_stationary_scan_is_unchanged():
    ranges = [1.0] * 8
    poses = [Pose2D(0.0, 0.0, 0.0, 0.0), Pose2D(1.0, 0.0, 0.0, 0.0)]

    corrected = deskew_ranges(
        ranges,
        angle_min=-math.pi,
        angle_increment=2.0 * math.pi / len(ranges),
        range_min=0.1,
        range_max=10.0,
        scan_start=0.0,
        time_increment=0.1,
        poses=poses,
    )

    assert list(corrected) == ranges


def test_translation_is_compensated_to_final_scan_pose():
    poses = [Pose2D(0.0, 0.0, 0.0, 0.0), Pose2D(1.0, 1.0, 0.0, 0.0)]

    corrected = deskew_ranges(
        [2.0, 2.0, 2.0, 2.0],
        angle_min=0.0,
        angle_increment=math.pi / 2.0,
        range_min=0.1,
        range_max=10.0,
        scan_start=0.0,
        time_increment=0.25,
        poses=poses,
    )

    assert corrected is not None
    assert math.isclose(corrected[0], 1.25, abs_tol=1e-6)
    assert math.isclose(corrected[3], 2.0, abs_tol=1e-6)


def test_missing_pose_coverage_returns_none():
    corrected = deskew_ranges(
        [1.0, 1.0],
        angle_min=0.0,
        angle_increment=math.pi,
        range_min=0.1,
        range_max=10.0,
        scan_start=0.0,
        time_increment=1.0,
        poses=[Pose2D(0.0, 0.0, 0.0, 0.0), Pose2D(0.5, 0.0, 0.0, 0.0)],
    )

    assert corrected is None
