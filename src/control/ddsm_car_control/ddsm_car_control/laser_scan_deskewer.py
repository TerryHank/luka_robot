#!/usr/bin/env python3

"""Motion-compensate a planar LaserScan using filtered wheel/IMU odometry."""

from __future__ import annotations

from array import array
from collections import deque
from dataclasses import dataclass
import math
from typing import Deque, Iterable, Optional, Sequence

import numpy as np
import rclpy
from nav_msgs.msg import Odometry
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import LaserScan


@dataclass(frozen=True)
class Pose2D:
    stamp: float
    x: float
    y: float
    yaw: float


def normalize_angle(value: float) -> float:
    return math.atan2(math.sin(value), math.cos(value))


def interpolate_pose(before: Pose2D, after: Pose2D, stamp: float) -> Pose2D:
    if after.stamp <= before.stamp:
        return Pose2D(stamp, before.x, before.y, before.yaw)
    ratio = min(max((stamp - before.stamp) / (after.stamp - before.stamp), 0.0), 1.0)
    yaw_delta = normalize_angle(after.yaw - before.yaw)
    return Pose2D(
        stamp,
        before.x + ratio * (after.x - before.x),
        before.y + ratio * (after.y - before.y),
        normalize_angle(before.yaw + ratio * yaw_delta),
    )


def pose_at(poses: Sequence[Pose2D], stamp: float) -> Optional[Pose2D]:
    if not poses or stamp < poses[0].stamp or stamp > poses[-1].stamp:
        return None
    for index in range(1, len(poses)):
        if poses[index].stamp >= stamp:
            return interpolate_pose(poses[index - 1], poses[index], stamp)
    return poses[-1]


def sample_poses(
    poses: Sequence[Pose2D], start: float, increment: float, count: int
) -> Optional[list[Pose2D]]:
    if not poses or count <= 0:
        return None
    end = start + (count - 1) * increment
    if start < poses[0].stamp or end > poses[-1].stamp:
        return None
    result = []
    pose_index = 1
    for beam_index in range(count):
        stamp = start + beam_index * increment
        while pose_index < len(poses) and poses[pose_index].stamp < stamp:
            pose_index += 1
        if pose_index >= len(poses):
            return None
        result.append(interpolate_pose(poses[pose_index - 1], poses[pose_index], stamp))
    return result


def deskew_ranges(
    ranges: Sequence[float],
    *,
    angle_min: float,
    angle_increment: float,
    range_min: float,
    range_max: float,
    scan_start: float,
    time_increment: float,
    poses: Sequence[Pose2D],
    laser_x: float = 0.0,
    laser_y: float = 0.0,
    laser_yaw: float = 0.0,
) -> Optional[array]:
    """Reproject every beam into the laser frame at the final beam time."""
    if not ranges or angle_increment == 0.0 or time_increment <= 0.0:
        return None

    reference_stamp = scan_start + (len(ranges) - 1) * time_increment
    if not poses or scan_start < poses[0].stamp or reference_stamp > poses[-1].stamp:
        return None

    pose_stamps = np.fromiter((pose.stamp for pose in poses), dtype=np.float64)
    pose_x = np.fromiter((pose.x for pose in poses), dtype=np.float64)
    pose_y = np.fromiter((pose.y for pose in poses), dtype=np.float64)
    pose_yaw = np.unwrap(
        np.fromiter((pose.yaw for pose in poses), dtype=np.float64)
    )
    beam_stamps = scan_start + np.arange(len(ranges), dtype=np.float64) * time_increment
    beam_x = np.interp(beam_stamps, pose_stamps, pose_x)
    beam_y = np.interp(beam_stamps, pose_stamps, pose_y)
    beam_yaw = np.interp(beam_stamps, pose_stamps, pose_yaw)
    reference = Pose2D(
        reference_stamp,
        float(beam_x[-1]),
        float(beam_y[-1]),
        float(beam_yaw[-1]),
    )

    sensor_ref_yaw = reference.yaw + laser_yaw
    sensor_ref_x = reference.x + math.cos(reference.yaw) * laser_x - math.sin(reference.yaw) * laser_y
    sensor_ref_y = reference.y + math.sin(reference.yaw) * laser_x + math.cos(reference.yaw) * laser_y
    cos_ref = math.cos(sensor_ref_yaw)
    sin_ref = math.sin(sensor_ref_yaw)
    output = np.full(len(ranges), np.inf, dtype=np.float64)
    full_circle = abs(angle_increment * len(ranges)) >= (2.0 * math.pi - 0.05)
    distances = np.asarray(ranges, dtype=np.float64)
    valid = np.isfinite(distances) & (distances >= range_min) & (distances <= range_max)
    if not np.any(valid):
        return array("f", output)

    indices = np.flatnonzero(valid)
    valid_ranges = distances[valid]
    beam_angles = angle_min + indices * angle_increment + laser_yaw
    point_base_x = laser_x + np.cos(beam_angles) * valid_ranges
    point_base_y = laser_y + np.sin(beam_angles) * valid_ranges
    cos_base = np.cos(beam_yaw[valid])
    sin_base = np.sin(beam_yaw[valid])
    point_odom_x = beam_x[valid] + cos_base * point_base_x - sin_base * point_base_y
    point_odom_y = beam_y[valid] + sin_base * point_base_x + cos_base * point_base_y
    delta_x = point_odom_x - sensor_ref_x
    delta_y = point_odom_y - sensor_ref_y
    point_ref_x = cos_ref * delta_x + sin_ref * delta_y
    point_ref_y = -sin_ref * delta_x + cos_ref * delta_y
    corrected_ranges = np.hypot(point_ref_x, point_ref_y)
    corrected_angles = np.arctan2(point_ref_y, point_ref_x)
    corrected_indices = np.rint(
        (corrected_angles - angle_min) / angle_increment
    ).astype(np.int64)
    if full_circle:
        corrected_indices %= len(output)
        output_valid = np.ones(corrected_indices.shape, dtype=bool)
    else:
        output_valid = (corrected_indices >= 0) & (corrected_indices < len(output))
    np.minimum.at(
        output,
        corrected_indices[output_valid],
        corrected_ranges[output_valid],
    )
    return array("f", output)


def stamp_to_seconds(stamp) -> float:
    return float(stamp.sec) + float(stamp.nanosec) * 1e-9


def quaternion_to_yaw(orientation) -> float:
    siny_cosp = 2.0 * (
        orientation.w * orientation.z + orientation.x * orientation.y
    )
    cosy_cosp = 1.0 - 2.0 * (
        orientation.y * orientation.y + orientation.z * orientation.z
    )
    return math.atan2(siny_cosp, cosy_cosp)


class LaserScanDeskewer(Node):
    def __init__(self) -> None:
        super().__init__("laser_scan_deskewer")
        self.declare_parameter("input_topic", "/scan_raw")
        self.declare_parameter("output_topic", "/scan")
        self.declare_parameter("odom_topic", "/odometry/filtered")
        self.declare_parameter("laser_x", -0.065)
        self.declare_parameter("laser_y", 0.0)
        self.declare_parameter("laser_yaw", 0.0)
        self.declare_parameter("pose_buffer_seconds", 3.0)
        self.declare_parameter("max_pending_scans", 1)
        self.declare_parameter("stationary_translation_threshold", 0.005)
        self.declare_parameter("stationary_rotation_threshold", 0.005)

        self.laser_x = float(self.get_parameter("laser_x").value)
        self.laser_y = float(self.get_parameter("laser_y").value)
        self.laser_yaw = float(self.get_parameter("laser_yaw").value)
        self.pose_buffer_seconds = float(self.get_parameter("pose_buffer_seconds").value)
        self.max_pending_scans = int(self.get_parameter("max_pending_scans").value)
        self.stationary_translation_threshold = max(
            0.0,
            float(self.get_parameter("stationary_translation_threshold").value),
        )
        self.stationary_rotation_threshold = max(
            0.0,
            float(self.get_parameter("stationary_rotation_threshold").value),
        )
        input_topic = str(self.get_parameter("input_topic").value)
        output_topic = str(self.get_parameter("output_topic").value)
        odom_topic = str(self.get_parameter("odom_topic").value)

        sensor_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            reliability=ReliabilityPolicy.BEST_EFFORT,
        )
        odom_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=100,
            reliability=ReliabilityPolicy.RELIABLE,
        )
        output_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
            reliability=ReliabilityPolicy.RELIABLE,
        )
        self.poses: Deque[Pose2D] = deque()
        self.pending_scans: Deque[LaserScan] = deque()
        self.publisher = self.create_publisher(LaserScan, output_topic, output_qos)
        self.create_subscription(LaserScan, input_topic, self.on_scan, sensor_qos)
        self.create_subscription(Odometry, odom_topic, self.on_odom, odom_qos)
        self.fallback_count = 0
        self.dropped_count = 0
        self.corrected_count = 0
        self.get_logger().info(
            f"Laser scan deskewer ready | input={input_topic} output={output_topic} "
            f"odom={odom_topic} laser=({self.laser_x:.3f},{self.laser_y:.3f},"
            f"{self.laser_yaw:.3f})"
        )

    def on_odom(self, msg: Odometry) -> None:
        pose = msg.pose.pose
        sample = Pose2D(
            stamp_to_seconds(msg.header.stamp),
            float(pose.position.x),
            float(pose.position.y),
            quaternion_to_yaw(pose.orientation),
        )
        if self.poses and sample.stamp < self.poses[-1].stamp:
            self.poses.clear()
        self.poses.append(sample)
        cutoff = sample.stamp - self.pose_buffer_seconds
        while len(self.poses) > 2 and self.poses[1].stamp < cutoff:
            self.poses.popleft()
        self.process_pending()

    def on_scan(self, msg: LaserScan) -> None:
        self.pending_scans.append(msg)
        while len(self.pending_scans) > self.max_pending_scans:
            self.pending_scans.popleft()
            self.dropped_count += 1
            if self.dropped_count == 1 or self.dropped_count % 100 == 0:
                self.get_logger().warning(
                    "Dropped stale scan while waiting for odometry "
                    f"(count={self.dropped_count})"
                )
        self.process_pending()

    def process_pending(self) -> None:
        if not self.pending_scans or not self.poses:
            return
        while self.pending_scans:
            scan = self.pending_scans[0]
            start = stamp_to_seconds(scan.header.stamp)
            increment = float(scan.time_increment)
            if increment <= 0.0 and len(scan.ranges) > 1:
                increment = float(scan.scan_time) / float(len(scan.ranges) - 1)
            end = start + max(len(scan.ranges) - 1, 0) * increment
            if self.poses[-1].stamp < end:
                return
            self.pending_scans.popleft()
            poses = list(self.poses)
            start_pose = pose_at(poses, start)
            end_pose = pose_at(poses, end)
            if start_pose is not None and end_pose is not None:
                translation = math.hypot(
                    end_pose.x - start_pose.x,
                    end_pose.y - start_pose.y,
                )
                rotation = abs(normalize_angle(end_pose.yaw - start_pose.yaw))
                if (
                    translation <= self.stationary_translation_threshold
                    and rotation <= self.stationary_rotation_threshold
                ):
                    self.publisher.publish(scan)
                    continue
            corrected = deskew_ranges(
                scan.ranges,
                angle_min=float(scan.angle_min),
                angle_increment=float(scan.angle_increment),
                range_min=float(scan.range_min),
                range_max=float(scan.range_max),
                scan_start=start,
                time_increment=increment,
                poses=poses,
                laser_x=self.laser_x,
                laser_y=self.laser_y,
                laser_yaw=self.laser_yaw,
            )
            if corrected is None:
                self.publish_raw(scan, "missing bracketing odometry")
                continue
            scan.ranges = corrected
            scan.header.stamp.sec = int(end)
            scan.header.stamp.nanosec = int(round((end - int(end)) * 1e9))
            if scan.header.stamp.nanosec >= 1_000_000_000:
                scan.header.stamp.sec += 1
                scan.header.stamp.nanosec -= 1_000_000_000
            scan.time_increment = 0.0
            self.publisher.publish(scan)
            self.corrected_count += 1
            if self.corrected_count == 1:
                self.get_logger().info("Publishing motion-compensated laser scans")

    def publish_raw(self, scan: LaserScan, reason: str) -> None:
        self.publisher.publish(scan)
        self.fallback_count += 1
        if self.fallback_count == 1 or self.fallback_count % 100 == 0:
            self.get_logger().warning(
                f"Deskew fallback to raw scan: {reason} (count={self.fallback_count})"
            )


def main(args: Optional[Iterable[str]] = None) -> None:
    rclpy.init(args=args)
    node = LaserScanDeskewer()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
