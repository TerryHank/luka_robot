import math
from typing import Iterable, Sequence, Tuple


Point = Tuple[float, float, float]


def transform_point(point: Sequence[float], translation, rotation) -> Point:
    """Transform one XYZ point using geometry-message-like objects."""
    x, y, z = float(point[0]), float(point[1]), float(point[2])
    qx, qy, qz, qw = rotation.x, rotation.y, rotation.z, rotation.w
    tx = 2.0 * (qy * z - qz * y)
    ty = 2.0 * (qz * x - qx * z)
    tz = 2.0 * (qx * y - qy * x)
    rx = x + qw * tx + (qy * tz - qz * ty)
    ry = y + qw * ty + (qz * tx - qx * tz)
    rz = z + qw * tz + (qx * ty - qy * tx)
    return (
        rx + translation.x,
        ry + translation.y,
        rz + translation.z,
    )


def select_obstacle_points(
    points: Iterable[Sequence[float]],
    translation,
    rotation,
    *,
    min_x: float,
    max_x: float,
    max_abs_y: float,
    min_z: float,
    max_z: float,
    corridor_half_width: float,
) -> Tuple[list[Point], float]:
    """Return bounded base-frame points and nearest distance in the drive corridor."""
    selected: list[Point] = []
    nearest = math.inf
    for point in points:
        x, y, z = transform_point(point, translation, rotation)
        if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(z)):
            continue
        if not (
            min_x <= x <= max_x
            and abs(y) <= max_abs_y
            and min_z <= z <= max_z
        ):
            continue
        selected.append((x, y, z))
        if abs(y) <= corridor_half_width:
            nearest = min(nearest, x)
    return selected, nearest


def project_points_to_scan(
    points: Iterable[Sequence[float]],
    translation,
    rotation,
    *,
    angle_min: float,
    angle_increment: float,
    beam_count: int,
    range_min: float,
    range_max: float,
) -> list[float]:
    """Project base-frame XYZ points into the coordinate frame of a LaserScan."""
    ranges = [math.inf] * beam_count
    if beam_count <= 0 or angle_increment == 0.0:
        return ranges

    for point in points:
        x, y, _ = transform_point(point, translation, rotation)
        distance = math.hypot(x, y)
        if not (math.isfinite(distance) and range_min <= distance <= range_max):
            continue
        angle = math.atan2(y, x)
        index = int(round((angle - angle_min) / angle_increment))
        if 0 <= index < beam_count:
            ranges[index] = min(ranges[index], distance)
    return ranges


def confirm_depth_ranges(
    current: Sequence[float],
    previous: Sequence[float] | None,
    *,
    distance_tolerance: float,
    neighbor_radius: int = 2,
) -> list[float]:
    """Keep depth returns observed in two consecutive clouds."""
    confirmed = [math.inf] * len(current)
    if previous is None or len(previous) != len(current):
        return confirmed

    for index, distance in enumerate(current):
        if not math.isfinite(distance):
            continue
        first = max(0, index - neighbor_radius)
        last = min(len(previous), index + neighbor_radius + 1)
        if any(
            math.isfinite(old) and abs(distance - old) <= distance_tolerance
            for old in previous[first:last]
        ):
            confirmed[index] = distance
    return confirmed


def fuse_scan_ranges(
    lidar_ranges: Sequence[float], depth_ranges: Sequence[float]
) -> list[float]:
    """Use the nearest valid return in every matching lidar/depth beam."""
    fused = list(lidar_ranges)
    if len(depth_ranges) != len(fused):
        return fused
    for index, depth_distance in enumerate(depth_ranges):
        if not math.isfinite(depth_distance):
            continue
        lidar_distance = fused[index]
        if not math.isfinite(lidar_distance) or depth_distance < lidar_distance:
            fused[index] = depth_distance
    return fused
