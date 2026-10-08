#!/usr/bin/env python3
import math
import time

import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import LaserScan
from std_msgs.msg import String


def _normalise_angle(angle):
    return np.arctan2(np.sin(angle), np.cos(angle))


def _sector_mask(angles, minimum, maximum):
    """Return angles inside a possibly wrapping angular sector."""
    angles = _normalise_angle(angles)
    minimum = math.atan2(math.sin(minimum), math.cos(minimum))
    maximum = math.atan2(math.sin(maximum), math.cos(maximum))
    if minimum <= maximum:
        return (angles >= minimum) & (angles <= maximum)
    return (angles >= minimum) | (angles <= maximum)


class DualLaserFusion(Node):
    """Fuse a navigation laser and a masked low laser into one LaserScan."""

    def __init__(self):
        super().__init__('dual_laser_fusion')
        self.declare_parameter('primary_topic', '/scan')
        self.declare_parameter('secondary_topic', '/scan_low_raw')
        self.declare_parameter('secondary_filtered_topic', '/scan_low_filtered')
        self.declare_parameter('output_topic', '/scan_obstacle_fused')
        self.declare_parameter('secondary_x', 0.0)
        self.declare_parameter('secondary_y', 0.0)
        self.declare_parameter('secondary_yaw', 0.0)
        self.declare_parameter('secondary_keep_min_deg', -180.0)
        self.declare_parameter('secondary_keep_max_deg', 180.0)
        self.declare_parameter('secondary_min_range', 0.08)
        self.declare_parameter('secondary_max_range', 8.0)
        self.declare_parameter('secondary_self_filter_enabled', True)
        self.declare_parameter('secondary_self_filter_min_x', -0.30)
        self.declare_parameter('secondary_self_filter_max_x', 0.30)
        self.declare_parameter('secondary_self_filter_min_y', -0.21)
        self.declare_parameter('secondary_self_filter_max_y', 0.21)
        self.declare_parameter('secondary_timeout', 0.25)
        self.declare_parameter('secondary_sync_tolerance', 0.15)
        self.declare_parameter('fused_publish_rate', 5.0)
        self.declare_parameter('status_rate', 1.0)

        self.secondary_x = float(self.get_parameter('secondary_x').value)
        self.secondary_y = float(self.get_parameter('secondary_y').value)
        self.secondary_yaw = float(self.get_parameter('secondary_yaw').value)
        self.keep_min = math.radians(
            float(self.get_parameter('secondary_keep_min_deg').value)
        )
        self.keep_max = math.radians(
            float(self.get_parameter('secondary_keep_max_deg').value)
        )
        self.secondary_min_range = float(
            self.get_parameter('secondary_min_range').value
        )
        self.secondary_max_range = float(
            self.get_parameter('secondary_max_range').value
        )
        self.secondary_self_filter_enabled = bool(
            self.get_parameter('secondary_self_filter_enabled').value
        )
        self.secondary_self_filter_min_x = float(
            self.get_parameter('secondary_self_filter_min_x').value
        )
        self.secondary_self_filter_max_x = float(
            self.get_parameter('secondary_self_filter_max_x').value
        )
        self.secondary_self_filter_min_y = float(
            self.get_parameter('secondary_self_filter_min_y').value
        )
        self.secondary_self_filter_max_y = float(
            self.get_parameter('secondary_self_filter_max_y').value
        )
        self.secondary_timeout = float(self.get_parameter('secondary_timeout').value)
        self.secondary_sync_tolerance = float(
            self.get_parameter('secondary_sync_tolerance').value
        )
        self.fused_publish_rate = max(
            0.0, float(self.get_parameter('fused_publish_rate').value)
        )

        self.secondary_scan = None
        self.secondary_received_at = 0.0
        self.primary_count = 0
        self.secondary_count = 0
        self.fused_count = 0
        self.secondary_points_last = 0
        self.secondary_self_filtered_last = 0
        self.secondary_filtered_count = 0
        self.secondary_sync_delta_last = -1.0
        self.last_fused_publish_at = 0.0

        self.publisher = self.create_publisher(
            LaserScan, self.get_parameter('output_topic').value, qos_profile_sensor_data
        )
        self.secondary_filtered_publisher = self.create_publisher(
            LaserScan,
            self.get_parameter('secondary_filtered_topic').value,
            qos_profile_sensor_data,
        )
        self.status_publisher = self.create_publisher(
            String, '/dual_laser_fusion/status', 10
        )
        self.create_subscription(
            LaserScan,
            self.get_parameter('primary_topic').value,
            self.on_primary,
            qos_profile_sensor_data,
        )
        self.create_subscription(
            LaserScan,
            self.get_parameter('secondary_topic').value,
            self.on_secondary,
            qos_profile_sensor_data,
        )
        rate = max(0.2, float(self.get_parameter('status_rate').value))
        self.create_timer(1.0 / rate, self.publish_status)

    def on_secondary(self, msg):
        filtered, kept, self_filtered = self._filter_secondary(msg)
        self.secondary_scan = filtered
        self.secondary_received_at = time.monotonic()
        self.secondary_count += 1
        self.secondary_filtered_count += 1
        self.secondary_points_last = kept
        self.secondary_self_filtered_last = self_filtered
        self.secondary_filtered_publisher.publish(filtered)

    def on_primary(self, primary):
        self.primary_count += 1
        now = time.monotonic()
        if (
            self.fused_publish_rate > 0.0
            and self.last_fused_publish_at > 0.0
            and now - self.last_fused_publish_at < 1.0 / self.fused_publish_rate
        ):
            return
        self.last_fused_publish_at = now
        output = LaserScan()
        output.header = primary.header
        output.angle_min = primary.angle_min
        output.angle_max = primary.angle_max
        output.angle_increment = primary.angle_increment
        output.time_increment = primary.time_increment
        output.scan_time = primary.scan_time
        output.range_min = primary.range_min
        output.range_max = primary.range_max
        output.ranges = list(primary.ranges)
        output.intensities = list(primary.intensities)

        secondary = self.secondary_scan
        secondary_age = time.monotonic() - self.secondary_received_at
        sync_delta = self._stamp_delta(primary, secondary)
        self.secondary_sync_delta_last = sync_delta
        sync_ok = sync_delta < 0.0 or sync_delta <= self.secondary_sync_tolerance
        if (
            secondary is not None
            and secondary_age <= self.secondary_timeout
            and sync_ok
        ):
            self._merge_secondary(output, secondary)
            self.fused_count += 1
        self.publisher.publish(output)

    @staticmethod
    def _copy_scan(source, ranges):
        output = LaserScan()
        output.header = source.header
        output.angle_min = source.angle_min
        output.angle_max = source.angle_max
        output.angle_increment = source.angle_increment
        output.time_increment = source.time_increment
        output.scan_time = source.scan_time
        output.range_min = source.range_min
        output.range_max = source.range_max
        output.ranges = ranges
        output.intensities = list(source.intensities)
        return output

    @staticmethod
    def _stamp_delta(first, second):
        if first is None or second is None:
            return -1.0
        first_ns = first.header.stamp.sec * 1_000_000_000 + first.header.stamp.nanosec
        second_ns = second.header.stamp.sec * 1_000_000_000 + second.header.stamp.nanosec
        if first_ns <= 0 or second_ns <= 0:
            return -1.0
        return abs(first_ns - second_ns) / 1_000_000_000.0

    def _filter_secondary(self, secondary):
        count = len(secondary.ranges)
        if count == 0:
            return self._copy_scan(secondary, []), 0, 0

        indices = np.arange(count, dtype=np.float64)
        ranges = np.asarray(secondary.ranges, dtype=np.float64)
        angles = secondary.angle_min + indices * secondary.angle_increment
        valid = (
            np.isfinite(ranges)
            & (ranges >= max(secondary.range_min, self.secondary_min_range))
            & (ranges <= min(secondary.range_max, self.secondary_max_range))
            & _sector_mask(angles, self.keep_min, self.keep_max)
        )

        self_filtered_count = 0
        if self.secondary_self_filter_enabled and np.any(valid):
            transformed_angles = angles + self.secondary_yaw
            x = self.secondary_x + ranges * np.cos(transformed_angles)
            y = self.secondary_y + ranges * np.sin(transformed_angles)
            self_points = valid & (
                (x >= self.secondary_self_filter_min_x)
                & (x <= self.secondary_self_filter_max_x)
                & (y >= self.secondary_self_filter_min_y)
                & (y <= self.secondary_self_filter_max_y)
            )
            self_filtered_count = int(np.count_nonzero(self_points))
            valid &= ~self_points

        filtered_ranges = np.full(count, np.inf, dtype=np.float32)
        filtered_ranges[valid] = ranges[valid].astype(np.float32)
        return (
            self._copy_scan(secondary, filtered_ranges.tolist()),
            int(np.count_nonzero(valid)),
            self_filtered_count,
        )

    def _merge_secondary(self, output, secondary):
        count = len(secondary.ranges)
        if count == 0 or output.angle_increment <= 0.0 or not output.ranges:
            return 0

        indices = np.arange(count, dtype=np.float64)
        ranges = np.asarray(secondary.ranges, dtype=np.float64)
        angles = secondary.angle_min + indices * secondary.angle_increment
        valid = np.isfinite(ranges)
        if not np.any(valid):
            return 0

        ranges = ranges[valid]
        angles = angles[valid] + self.secondary_yaw
        x = self.secondary_x + ranges * np.cos(angles)
        y = self.secondary_y + ranges * np.sin(angles)
        fused_ranges = np.hypot(x, y)
        fused_angles = np.arctan2(y, x)
        bins = np.rint(
            (fused_angles - output.angle_min) / output.angle_increment
        ).astype(np.int64)
        valid_bins = (
            (bins >= 0)
            & (bins < len(output.ranges))
            & (fused_ranges >= output.range_min)
            & (fused_ranges <= output.range_max)
        )
        if not np.any(valid_bins):
            return 0

        bins = bins[valid_bins]
        fused_ranges = fused_ranges[valid_bins]
        low_by_bin = np.full(len(output.ranges), np.inf, dtype=np.float64)
        np.minimum.at(low_by_bin, bins, fused_ranges)
        primary_ranges = np.asarray(output.ranges, dtype=np.float64)
        primary_ranges[~np.isfinite(primary_ranges)] = np.inf
        output.ranges = np.minimum(primary_ranges, low_by_bin).astype(np.float32).tolist()
        return int(np.count_nonzero(np.isfinite(low_by_bin)))

    def publish_status(self):
        age = (
            time.monotonic() - self.secondary_received_at
            if self.secondary_received_at
            else -1.0
        )
        healthy = 0.0 <= age <= self.secondary_timeout
        msg = String()
        msg.data = (
            f"healthy={str(healthy).lower()} primary={self.primary_count} "
            f"secondary={self.secondary_count} fused={self.fused_count} "
            f"secondary_age={age:.3f} points={self.secondary_points_last} "
            f"self_filtered={self.secondary_self_filtered_last} "
            f"filtered={self.secondary_filtered_count} "
            f"sync_delta={self.secondary_sync_delta_last:.3f}"
        )
        self.status_publisher.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = DualLaserFusion()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
