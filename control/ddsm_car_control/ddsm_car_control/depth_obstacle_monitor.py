#!/usr/bin/env python3

import math

import numpy as np
import rclpy
from rclpy.duration import Duration
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from rclpy.time import Time
from sensor_msgs.msg import CameraInfo, Image, LaserScan
from std_msgs.msg import Bool, Float32
from tf2_ros import Buffer, TransformException, TransformListener

from .depth_geometry import (
    confirm_depth_ranges,
    fuse_scan_ranges,
    project_points_to_scan,
    select_obstacle_points,
    transform_point,
)


class DepthObstacleMonitor(Node):
    def __init__(self):
        super().__init__("depth_obstacle_monitor")
        self.declare_parameter("depth_image_topic", "/camera/depth/image_raw")
        self.declare_parameter("camera_info_topic", "/camera/depth/camera_info")
        self.declare_parameter("scan_input_topic", "/scan")
        self.declare_parameter("fused_scan_topic", "/scan_obstacle_fused")
        self.declare_parameter(
            "depth_scan_topic", "/depth_camera/confirmed_obstacle_scan"
        )
        self.declare_parameter("processing_rate", 12.0)
        self.declare_parameter("depth_unit_scale", 0.001)
        self.declare_parameter("base_frame", "base_link")
        self.declare_parameter("memory_frame", "odom")
        self.declare_parameter("obstacle_memory_duration", 2.5)
        self.declare_parameter("obstacle_memory_resolution", 0.05)
        self.declare_parameter("min_x", 0.12)
        self.declare_parameter("max_x", 3.0)
        self.declare_parameter("max_abs_y", 2.0)
        self.declare_parameter("min_z", 0.05)
        self.declare_parameter("max_z", 1.20)
        self.declare_parameter("corridor_half_width", 0.30)
        self.declare_parameter("stop_distance", 0.55)
        self.declare_parameter("sample_stride", 2)
        self.declare_parameter("depth_timeout", 2.0)
        self.declare_parameter("confirmation_distance_tolerance", 0.20)

        value = lambda name: self.get_parameter(name).value
        self.depth_image_topic = str(value("depth_image_topic"))
        self.camera_info_topic = str(value("camera_info_topic"))
        self.scan_input_topic = str(value("scan_input_topic"))
        self.fused_scan_topic = str(value("fused_scan_topic"))
        self.depth_scan_topic = str(value("depth_scan_topic"))
        processing_rate = max(0.1, float(value("processing_rate")))
        self.processing_period_ns = int(1_000_000_000 / processing_rate)
        self.depth_unit_scale = float(value("depth_unit_scale"))
        self.base_frame = str(value("base_frame"))
        self.memory_frame = str(value("memory_frame"))
        self.obstacle_memory_ns = int(
            float(value("obstacle_memory_duration")) * 1_000_000_000
        )
        self.obstacle_memory_resolution = max(
            0.01, float(value("obstacle_memory_resolution"))
        )
        self.min_x = float(value("min_x"))
        self.max_x = float(value("max_x"))
        self.max_abs_y = float(value("max_abs_y"))
        self.min_z = float(value("min_z"))
        self.max_z = float(value("max_z"))
        self.corridor_half_width = float(value("corridor_half_width"))
        self.stop_distance = float(value("stop_distance"))
        self.sample_stride = max(1, int(value("sample_stride")))
        self.depth_timeout_ns = int(float(value("depth_timeout")) * 1_000_000_000)
        self.confirmation_distance_tolerance = float(
            value("confirmation_distance_tolerance")
        )

        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        self.distance_pub = self.create_publisher(
            Float32, "/depth_camera/nearest_obstacle_distance", 10
        )
        self.blocked_pub = self.create_publisher(Bool, "/depth_camera/blocked", 10)
        self.fused_scan_pub = self.create_publisher(
            LaserScan, self.fused_scan_topic, qos_profile_sensor_data
        )
        self.depth_scan_pub = self.create_publisher(
            LaserScan, self.depth_scan_topic, qos_profile_sensor_data
        )
        self.depth_subscription = self.create_subscription(
            Image,
            self.depth_image_topic,
            self._depth_callback,
            qos_profile_sensor_data,
        )
        self.camera_info_subscription = self.create_subscription(
            CameraInfo,
            self.camera_info_topic,
            self._camera_info_callback,
            qos_profile_sensor_data,
        )
        self.scan_subscription = self.create_subscription(
            LaserScan,
            self.scan_input_topic,
            self._scan_callback,
            qos_profile_sensor_data,
        )
        self._scan_geometry = None
        self._previous_depth_ranges = None
        self._confirmed_depth_ranges = None
        self._persistent_depth_cells = {}
        self._latest_depth_ns = 0
        self._depth_count = 0
        self._camera_intrinsics = None
        self._last_depth_process_ns = 0
        self._scan_count = 0
        self._last_status_ns = self.get_clock().now().nanoseconds
        self._last_tf_warning_ns = 0
        self.get_logger().info(
            f"Monitoring {self.depth_image_topic}; fused obstacle scan: {self.fused_scan_topic}; "
            f"persistent depth scan: {self.depth_scan_topic}; "
            f"memory={self.obstacle_memory_ns / 1_000_000_000.0:.1f}s "
            f"frame={self.memory_frame}"
        )

    def _remember_depth_ranges(self, stamp, geometry, ranges) -> None:
        try:
            transform = self.tf_buffer.lookup_transform(
                self.memory_frame,
                geometry[0],
                Time(),
                timeout=Duration(seconds=0.05),
            )
        except TransformException as exc:
            now_ns = self.get_clock().now().nanoseconds
            if now_ns - self._last_tf_warning_ns >= 5_000_000_000:
                self.get_logger().warning(
                    f"Waiting for {self.memory_frame} <- {geometry[0]}: {exc}"
                )
                self._last_tf_warning_ns = now_ns
            return

        now_ns = self.get_clock().now().nanoseconds
        angle = geometry[1]
        for distance in ranges:
            if math.isfinite(distance):
                point = transform_point(
                    (distance * math.cos(angle), distance * math.sin(angle), 0.0),
                    transform.transform.translation,
                    transform.transform.rotation,
                )
                cell = (
                    int(round(point[0] / self.obstacle_memory_resolution)),
                    int(round(point[1] / self.obstacle_memory_resolution)),
                )
                self._persistent_depth_cells[cell] = (point[0], point[1], now_ns)
            angle += geometry[2]

    def _persistent_depth_ranges(self, message, geometry):
        now_ns = self.get_clock().now().nanoseconds
        expired = [
            cell
            for cell, (_, _, seen_ns) in self._persistent_depth_cells.items()
            if now_ns - seen_ns > self.obstacle_memory_ns
        ]
        for cell in expired:
            del self._persistent_depth_cells[cell]

        if not self._persistent_depth_cells:
            return [math.inf] * geometry[3]

        try:
            transform = self.tf_buffer.lookup_transform(
                geometry[0],
                self.memory_frame,
                Time(),
                timeout=Duration(seconds=0.05),
            )
        except TransformException as exc:
            if now_ns - self._last_tf_warning_ns >= 5_000_000_000:
                self.get_logger().warning(
                    f"Waiting for {geometry[0]} <- {self.memory_frame}: {exc}"
                )
                self._last_tf_warning_ns = now_ns
            return [math.inf] * geometry[3]

        points = (
            (x, y, 0.0) for x, y, _ in self._persistent_depth_cells.values()
        )
        return project_points_to_scan(
            points,
            transform.transform.translation,
            transform.transform.rotation,
            angle_min=geometry[1],
            angle_increment=geometry[2],
            beam_count=geometry[3],
            range_min=max(geometry[4], self.min_x),
            range_max=min(geometry[5], self.max_x),
        )

    def _publish_depth_scan(self, stamp, geometry, ranges) -> None:
        depth_scan = LaserScan()
        depth_scan.header.stamp = stamp
        depth_scan.header.frame_id = geometry[0]
        depth_scan.angle_min = geometry[1]
        depth_scan.angle_increment = geometry[2]
        depth_scan.angle_max = (
            geometry[1] + geometry[2] * (geometry[3] - 1)
            if geometry[3] > 0
            else geometry[1]
        )
        depth_scan.range_min = geometry[4]
        depth_scan.range_max = geometry[5]
        depth_scan.ranges = list(ranges)
        self.depth_scan_pub.publish(depth_scan)

    @staticmethod
    def _geometry(message: LaserScan):
        return (
            message.header.frame_id,
            float(message.angle_min),
            float(message.angle_increment),
            len(message.ranges),
            float(message.range_min),
            float(message.range_max),
        )

    def _scan_callback(self, message: LaserScan) -> None:
        self._scan_count += 1
        geometry = self._geometry(message)
        if geometry != self._scan_geometry:
            self._scan_geometry = geometry
            self._previous_depth_ranges = None
            self._confirmed_depth_ranges = None
            self._persistent_depth_cells.clear()

        depth_ranges = self._persistent_depth_ranges(message, geometry)

        fused = LaserScan()
        fused.header = message.header
        fused.angle_min = message.angle_min
        fused.angle_max = message.angle_max
        fused.angle_increment = message.angle_increment
        fused.time_increment = message.time_increment
        fused.scan_time = message.scan_time
        fused.range_min = message.range_min
        fused.range_max = message.range_max
        fused.ranges = fuse_scan_ranges(message.ranges, depth_ranges)
        fused.intensities = message.intensities
        self.fused_scan_pub.publish(fused)
        self._publish_depth_scan(message.header.stamp, geometry, depth_ranges)

        now_ns = self.get_clock().now().nanoseconds
        if now_ns - self._last_status_ns >= 10_000_000_000:
            confirmed_beams = sum(
                math.isfinite(distance) for distance in (depth_ranges or ())
            )
            depth_age = (
                (now_ns - self._latest_depth_ns) / 1_000_000_000.0
                if self._latest_depth_ns
                else math.inf
            )
            self.get_logger().info(
                "Depth fusion status: "
                f"depth_images={self._depth_count} scans={self._scan_count} "
                f"persistent_beams={confirmed_beams} "
                f"memory_cells={len(self._persistent_depth_cells)} "
                f"depth_age={depth_age:.2f}s"
            )
            self._last_status_ns = now_ns

    def _camera_info_callback(self, message: CameraInfo) -> None:
        if message.k[0] > 0.0 and message.k[4] > 0.0:
            self._camera_intrinsics = (
                float(message.k[0]),
                float(message.k[4]),
                float(message.k[2]),
                float(message.k[5]),
            )

    def _depth_points(self, message: Image):
        encoding = message.encoding.upper()
        if encoding in ("16UC1", "MONO16"):
            row_values = message.step // 2
            depth = np.frombuffer(message.data, dtype=np.uint16).reshape(
                message.height, row_values
            )[:, : message.width]
            if message.is_bigendian:
                depth = depth.byteswap()
            depth = depth.astype(np.float32) * self.depth_unit_scale
        elif encoding == "32FC1":
            row_values = message.step // 4
            depth = np.frombuffer(message.data, dtype=np.float32).reshape(
                message.height, row_values
            )[:, : message.width]
            if message.is_bigendian:
                depth = depth.byteswap()
        else:
            raise ValueError(f"unsupported depth encoding: {message.encoding}")

        fx, fy, cx, cy = self._camera_intrinsics
        rows = np.arange(0, message.height, self.sample_stride)
        columns = np.arange(0, message.width, self.sample_stride)
        vv, uu = np.meshgrid(rows, columns, indexing="ij")
        zz = depth[vv, uu]
        valid = np.isfinite(zz) & (zz > 0.0) & (zz <= self.max_x + 1.0)
        zz = zz[valid]
        uu = uu[valid]
        vv = vv[valid]
        xx = (uu.astype(np.float32) - cx) * zz / fx
        yy = (vv.astype(np.float32) - cy) * zz / fy
        return zip(xx.tolist(), yy.tolist(), zz.tolist())

    def _depth_callback(self, message: Image) -> None:
        now_ns = self.get_clock().now().nanoseconds
        if now_ns - self._last_depth_process_ns < self.processing_period_ns:
            return
        self._last_depth_process_ns = now_ns
        self._depth_count += 1
        if self._camera_intrinsics is None:
            self.get_logger().warning("Waiting for depth camera intrinsics")
            return
        if not message.header.frame_id:
            self.get_logger().warning("Depth image has no frame_id")
            return
        try:
            transform = self.tf_buffer.lookup_transform(
                self.base_frame,
                message.header.frame_id,
                Time.from_msg(message.header.stamp),
                timeout=Duration(seconds=0.15),
            )
        except TransformException as exc:
            now_ns = self.get_clock().now().nanoseconds
            if now_ns - self._last_tf_warning_ns >= 5_000_000_000:
                self.get_logger().warning(
                    f"Waiting for {self.base_frame} <- {message.header.frame_id}: {exc}"
                )
                self._last_tf_warning_ns = now_ns
            return

        try:
            sampled_points = self._depth_points(message)
        except (ValueError, TypeError) as exc:
            self.get_logger().error(str(exc))
            return
        filtered, nearest = select_obstacle_points(
            sampled_points,
            transform.transform.translation,
            transform.transform.rotation,
            min_x=self.min_x,
            max_x=self.max_x,
            max_abs_y=self.max_abs_y,
            min_z=self.min_z,
            max_z=self.max_z,
            corridor_half_width=self.corridor_half_width,
        )

        geometry = self._scan_geometry
        if geometry is not None and geometry[0]:
            try:
                scan_transform = self.tf_buffer.lookup_transform(
                    geometry[0],
                    self.base_frame,
                    Time.from_msg(message.header.stamp),
                    timeout=Duration(seconds=0.05),
                )
                current_depth_ranges = project_points_to_scan(
                    filtered,
                    scan_transform.transform.translation,
                    scan_transform.transform.rotation,
                    angle_min=geometry[1],
                    angle_increment=geometry[2],
                    beam_count=geometry[3],
                    range_min=max(geometry[4], self.min_x),
                    range_max=min(geometry[5], self.max_x),
                )
                self._confirmed_depth_ranges = confirm_depth_ranges(
                    current_depth_ranges,
                    self._previous_depth_ranges,
                    distance_tolerance=self.confirmation_distance_tolerance,
                )
                self._previous_depth_ranges = current_depth_ranges
                self._latest_depth_ns = self.get_clock().now().nanoseconds
                self._remember_depth_ranges(
                    message.header.stamp,
                    geometry,
                    self._confirmed_depth_ranges,
                )
            except TransformException as exc:
                now_ns = self.get_clock().now().nanoseconds
                if now_ns - self._last_tf_warning_ns >= 5_000_000_000:
                    self.get_logger().warning(
                        f"Waiting for {geometry[0]} <- {self.base_frame}: {exc}"
                    )
                    self._last_tf_warning_ns = now_ns

        distance = Float32()
        distance.data = float(nearest) if math.isfinite(nearest) else -1.0
        self.distance_pub.publish(distance)

        blocked = Bool()
        blocked.data = math.isfinite(nearest) and nearest <= self.stop_distance
        self.blocked_pub.publish(blocked)


def main(args=None):
    rclpy.init(args=args)
    node = DepthObstacleMonitor()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
