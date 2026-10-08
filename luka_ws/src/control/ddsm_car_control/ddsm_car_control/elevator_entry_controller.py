#!/usr/bin/env python3

import json
import math
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import rclpy
import numpy as np
from action_msgs.msg import GoalStatus
from geometry_msgs.msg import PoseStamped, Twist
from nav_msgs.msg import Odometry
from nav2_msgs.action import ComputePathToPose, NavigateToPose
from rclpy.action import ActionClient
from rclpy.node import Node
from rclpy.qos import (
    DurabilityPolicy,
    QoSProfile,
    ReliabilityPolicy,
    qos_profile_sensor_data,
)
from sensor_msgs.msg import CameraInfo, Image, LaserScan
from std_msgs.msg import Empty, String
from std_srvs.srv import Empty as EmptyService


class EntryState(str, Enum):
    IDLE = "idle"
    WAIT_SAFE = "wait_safe"
    ALIGN = "align"
    ENTER = "enter"
    BLOCKED = "blocked"
    VERIFY = "verify"
    NAVIGATING = "navigating"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass
class ElevatorSafety:
    available: bool = False
    door: str = "unknown"
    car_present: bool = False
    motion: str = "unknown"

    @property
    def safe_to_enter(self) -> bool:
        return (
            self.available
            and self.door == "open"
            and self.car_present
            and self.motion == "stopped"
        )


def normalize_angle(angle: float) -> float:
    return math.atan2(math.sin(angle), math.cos(angle))


def quaternion_to_yaw(x: float, y: float, z: float, w: float) -> float:
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


def nav2_path_is_valid(status: int, pose_count: int) -> bool:
    return status == GoalStatus.STATUS_SUCCEEDED and pose_count > 0


def corridor_is_clear(
    scan: LaserScan,
    clearance_distance: float,
    half_width: float,
    min_x: float = 0.05,
    min_blocking_points: int = 1,
) -> bool:
    angle = scan.angle_min
    consecutive_blocking_points = 0
    for distance in scan.ranges:
        blocking = False
        if math.isfinite(distance) and scan.range_min <= distance <= scan.range_max:
            x = distance * math.cos(angle)
            y = distance * math.sin(angle)
            if min_x <= x <= clearance_distance and abs(y) <= half_width:
                blocking = True
        if blocking:
            consecutive_blocking_points += 1
            if consecutive_blocking_points >= max(1, min_blocking_points):
                return False
        else:
            consecutive_blocking_points = 0
        angle += scan.angle_increment
    return True


def lidar_door_is_open(
    scan: LaserScan,
    *,
    check_distance: float,
    half_width: float,
    min_blocking_points: int,
) -> bool:
    angle = scan.angle_min
    blocking_points = 0
    for distance in scan.ranges:
        if math.isfinite(distance) and scan.range_min <= distance <= scan.range_max:
            x = distance * math.cos(angle)
            y = distance * math.sin(angle)
            if 0.05 <= x <= check_distance and abs(y) <= half_width:
                blocking_points += 1
                if blocking_points >= max(1, min_blocking_points):
                    return False
        angle += scan.angle_increment
    return True


def count_cabin_floor_points(
    depth_m: np.ndarray,
    *,
    fx: float,
    fy: float,
    cx: float,
    cy: float,
    camera_forward_offset: float,
    camera_height: float,
    min_x: float,
    max_x: float,
    half_width: float,
    z_tolerance: float,
) -> int:
    if depth_m.ndim != 2 or fx <= 0.0 or fy <= 0.0:
        return 0
    rows, cols = np.indices(depth_m.shape, dtype=np.float32)
    base_x = depth_m + camera_forward_offset
    base_y = -(cols - cx) * depth_m / fx
    base_z = camera_height - (rows - cy) * depth_m / fy
    floor_mask = (
        np.isfinite(depth_m)
        & (depth_m > 0.05)
        & (base_x >= min_x)
        & (base_x <= max_x)
        & (np.abs(base_y) <= half_width)
        & (np.abs(base_z) <= z_tolerance)
    )
    return int(np.count_nonzero(floor_mask))


def detect_depth_opening(
    depth_m: np.ndarray,
    *,
    cx: float,
    center_half_fraction: float,
    top_fraction: float,
    bottom_fraction: float,
    min_depth: float,
    min_valid_points: int,
) -> tuple[bool, int, float]:
    if depth_m.ndim != 2:
        return False, 0, 0.0
    height, width = depth_m.shape
    half_width = max(1, int(round(width * center_half_fraction)))
    left = max(0, int(round(cx)) - half_width)
    right = min(width, int(round(cx)) + half_width + 1)
    top = max(0, min(height, int(round(height * top_fraction))))
    bottom = max(top + 1, min(height, int(round(height * bottom_fraction))))
    roi = depth_m[top:bottom, left:right]
    valid = roi[np.isfinite(roi) & (roi > 0.05)]
    valid_points = int(valid.size)
    if valid_points < max(1, min_valid_points):
        return False, valid_points, 0.0
    median_depth = float(np.median(valid))
    return median_depth >= min_depth, valid_points, median_depth


class ElevatorEntryController(Node):
    def __init__(self) -> None:
        super().__init__("elevator_entry_controller")

        self.declare_parameter("auto_trigger", True)
        self.declare_parameter("entry_mode", "legacy")
        self.declare_parameter("door_status_source", "protocol")
        self.declare_parameter("control_rate", 20.0)
        self.declare_parameter("entry_speed", 0.10)
        self.declare_parameter("entry_distance", 0.95)
        self.declare_parameter("entry_timeout", 20.0)
        self.declare_parameter("blocked_timeout", 8.0)
        self.declare_parameter("align_duration", 0.5)
        self.declare_parameter("verify_duration", 0.8)
        self.declare_parameter("heading_kp", 1.2)
        self.declare_parameter("max_angular_speed", 0.20)
        self.declare_parameter("clearance_distance", 0.75)
        self.declare_parameter("min_blocking_points", 2)
        self.declare_parameter("robot_width", 0.38)
        self.declare_parameter("safety_margin", 0.08)
        self.declare_parameter("data_timeout", 0.8)
        self.declare_parameter("door_open_confirm_duration", 1.0)
        self.declare_parameter("door_scan_topic", "/scan")
        self.declare_parameter("door_check_distance", 1.50)
        self.declare_parameter("door_half_width", 0.27)
        self.declare_parameter("door_min_blocking_points", 20)
        self.declare_parameter("depth_topic", "/camera/depth/image_raw")
        self.declare_parameter("depth_info_topic", "/camera/depth/camera_info")
        self.declare_parameter("depth_process_rate", 5.0)
        self.declare_parameter("depth_scale", 0.001)
        self.declare_parameter("camera_forward_offset", 0.20)
        self.declare_parameter("camera_height", 0.32)
        self.declare_parameter("floor_min_x", 1.30)
        self.declare_parameter("floor_max_x", 1.55)
        self.declare_parameter("floor_half_width", 0.22)
        self.declare_parameter("floor_z_tolerance", 0.07)
        self.declare_parameter("floor_min_points", 80)
        self.declare_parameter("door_open_min_depth", 2.0)
        self.declare_parameter("door_open_min_valid_points", 500)
        self.declare_parameter("door_center_half_fraction", 0.18)
        self.declare_parameter("door_center_top_fraction", 0.15)
        self.declare_parameter("door_center_bottom_fraction", 0.94)
        self.declare_parameter("nav_goal_x", 0.0)
        self.declare_parameter("nav_goal_y", 0.0)
        self.declare_parameter("nav_goal_yaw", 0.0)
        self.declare_parameter("nav_path_check_period", 1.0)
        self.declare_parameter("nav_path_confirm_count", 2)
        self.declare_parameter("nav_navigation_timeout", 60.0)

        self.auto_trigger = bool(self.get_parameter("auto_trigger").value)
        self.entry_mode = str(self.get_parameter("entry_mode").value).strip().lower()
        if self.entry_mode not in {"legacy", "nav2"}:
            raise ValueError("entry_mode must be 'legacy' or 'nav2'")
        self.door_status_source = str(
            self.get_parameter("door_status_source").value
        ).strip().lower()
        if self.door_status_source not in {"protocol", "geometry", "lidar"}:
            raise ValueError(
                "door_status_source must be 'protocol', 'geometry', or 'lidar'"
            )
        self.entry_speed = float(self.get_parameter("entry_speed").value)
        self.entry_distance = float(self.get_parameter("entry_distance").value)
        self.entry_timeout = float(self.get_parameter("entry_timeout").value)
        self.blocked_timeout = float(self.get_parameter("blocked_timeout").value)
        self.align_duration = float(self.get_parameter("align_duration").value)
        self.verify_duration = float(self.get_parameter("verify_duration").value)
        self.heading_kp = float(self.get_parameter("heading_kp").value)
        self.max_angular_speed = float(self.get_parameter("max_angular_speed").value)
        self.clearance_distance = float(self.get_parameter("clearance_distance").value)
        self.min_blocking_points = max(
            1, int(self.get_parameter("min_blocking_points").value)
        )
        self.corridor_half_width = (
            float(self.get_parameter("robot_width").value) * 0.5
            + float(self.get_parameter("safety_margin").value)
        )
        self.data_timeout = float(self.get_parameter("data_timeout").value)
        self.door_open_confirm_duration = max(
            0.1, float(self.get_parameter("door_open_confirm_duration").value)
        )
        self.door_check_distance = float(
            self.get_parameter("door_check_distance").value
        )
        self.door_half_width = float(self.get_parameter("door_half_width").value)
        self.door_min_blocking_points = max(
            1, int(self.get_parameter("door_min_blocking_points").value)
        )
        depth_process_rate = max(
            1.0, float(self.get_parameter("depth_process_rate").value)
        )
        self.depth_process_period = 1.0 / depth_process_rate
        self.depth_scale = float(self.get_parameter("depth_scale").value)
        self.camera_forward_offset = float(
            self.get_parameter("camera_forward_offset").value
        )
        self.camera_height = float(self.get_parameter("camera_height").value)
        self.floor_min_x = float(self.get_parameter("floor_min_x").value)
        self.floor_max_x = float(self.get_parameter("floor_max_x").value)
        self.floor_half_width = float(self.get_parameter("floor_half_width").value)
        self.floor_z_tolerance = float(
            self.get_parameter("floor_z_tolerance").value
        )
        self.floor_min_points = max(
            1, int(self.get_parameter("floor_min_points").value)
        )
        self.door_open_min_depth = float(
            self.get_parameter("door_open_min_depth").value
        )
        self.door_open_min_valid_points = max(
            1, int(self.get_parameter("door_open_min_valid_points").value)
        )
        self.door_center_half_fraction = float(
            self.get_parameter("door_center_half_fraction").value
        )
        self.door_center_top_fraction = float(
            self.get_parameter("door_center_top_fraction").value
        )
        self.door_center_bottom_fraction = float(
            self.get_parameter("door_center_bottom_fraction").value
        )
        self.nav_goal_x = float(self.get_parameter("nav_goal_x").value)
        self.nav_goal_y = float(self.get_parameter("nav_goal_y").value)
        self.nav_goal_yaw = float(self.get_parameter("nav_goal_yaw").value)
        self.nav_path_check_period = max(
            0.2, float(self.get_parameter("nav_path_check_period").value)
        )
        self.nav_path_confirm_count = max(
            1, int(self.get_parameter("nav_path_confirm_count").value)
        )
        self.nav_navigation_timeout = max(
            5.0, float(self.get_parameter("nav_navigation_timeout").value)
        )

        transient_qos = QoSProfile(depth=1)
        transient_qos.reliability = ReliabilityPolicy.RELIABLE
        transient_qos.durability = DurabilityPolicy.TRANSIENT_LOCAL

        self.cmd_pub = self.create_publisher(Twist, "/cmd_vel", 10)
        self.entered_pub = self.create_publisher(Empty, "/hotel/elevator/entered", 10)
        self.status_pub = self.create_publisher(
            String, "/hotel/elevator/entry/status", transient_qos
        )
        self.failure_pub = self.create_publisher(
            String, "/hotel/elevator/entry/failure", transient_qos
        )
        self.path_client = ActionClient(
            self, ComputePathToPose, "/compute_path_to_pose"
        )
        self.nav_client = ActionClient(self, NavigateToPose, "/navigate_to_pose")

        self.create_subscription(
            String, "/hotel/elevator/status", self._on_elevator_status, transient_qos
        )
        self.create_subscription(
            String,
            "/hotel/floor_mission/status",
            self._on_mission_status,
            transient_qos,
        )
        self.scan_topic = "/scan_obstacle_fused"
        self.door_scan_topic = str(self.get_parameter("door_scan_topic").value)
        self.depth_info_topic = str(self.get_parameter("depth_info_topic").value)
        self.sensor_qos = qos_profile_sensor_data
        self.scan_subscription = None
        self.door_scan_subscription = None
        self.depth_info_subscription = None
        self.depth_topic = str(self.get_parameter("depth_topic").value)
        self.depth_subscription = None
        self.odom_subscription = None
        self.create_service(
            EmptyService, "/hotel/elevator/entry/start_now", self._on_start
        )
        self.create_service(
            EmptyService, "/hotel/elevator/entry/cancel_now", self._on_cancel
        )

        self.state = EntryState.IDLE
        self.elevator = ElevatorSafety()
        self.elevator_stamp = 0.0
        self.scan: Optional[LaserScan] = None
        self.scan_stamp = 0.0
        self.door_scan: Optional[LaserScan] = None
        self.door_scan_stamp = 0.0
        self.odom_xy: Optional[tuple[float, float]] = None
        self.odom_yaw: Optional[float] = None
        self.odom_stamp = 0.0
        self.depth_intrinsics: Optional[tuple[float, float, float, float]] = None
        self.depth_stamp = 0.0
        self.last_depth_processed = 0.0
        self.cabin_floor_points = 0
        self.cabin_floor_present = False
        self.depth_opening_present = False
        self.door_center_valid_points = 0
        self.door_center_median_depth = 0.0
        self.geometry_open_started = 0.0
        self.geometry_door_open = False
        self.start_xy: Optional[tuple[float, float]] = None
        self.target_yaw: Optional[float] = None
        self.state_started = time.monotonic()
        self.entry_started = 0.0
        self.blocked_started = 0.0
        self.last_mission_state = ""
        self.last_path_request = 0.0
        self.path_valid_count = 0
        self.path_send_future = None
        self.path_goal_handle = None
        self.path_result_future = None
        self.nav_send_future = None
        self.nav_goal_handle = None
        self.nav_result_future = None
        self.nav_started = 0.0
        self._publish_status("ready")

        rate = max(1.0, float(self.get_parameter("control_rate").value))
        self.control_timer = self.create_timer(1.0 / rate, self._tick)
        self.control_timer.cancel()

    def _now(self) -> float:
        return time.monotonic()

    def _fresh(self, stamp: float) -> bool:
        return stamp > 0.0 and self._now() - stamp <= self.data_timeout

    def _on_elevator_status(self, msg: String) -> None:
        try:
            data = json.loads(msg.data)
            self.elevator = ElevatorSafety(
                available=bool(data.get("available", False)),
                door=str(data.get("door", "unknown")).lower(),
                car_present=bool(data.get("car_present", False)),
                motion=str(data.get("motion", "unknown")).lower(),
            )
            self.elevator_stamp = self._now()
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            self.get_logger().warning(f"Invalid elevator status: {exc}")

    def _on_mission_status(self, msg: String) -> None:
        try:
            mission_state = str(json.loads(msg.data).get("state", ""))
        except (TypeError, ValueError, json.JSONDecodeError):
            return
        transitioned = (
            mission_state == "ready_to_enter"
            and self.last_mission_state != "ready_to_enter"
        )
        self.last_mission_state = mission_state
        if self.auto_trigger and transitioned and self.state == EntryState.IDLE:
            self._begin("mission_ready_to_enter")

    def _on_scan(self, msg: LaserScan) -> None:
        self.scan = msg
        self.scan_stamp = self._now()

    def _on_door_scan(self, msg: LaserScan) -> None:
        self.door_scan = msg
        self.door_scan_stamp = self._now()

    def _on_odom(self, msg: Odometry) -> None:
        pose = msg.pose.pose
        self.odom_xy = (pose.position.x, pose.position.y)
        self.odom_yaw = quaternion_to_yaw(
            pose.orientation.x,
            pose.orientation.y,
            pose.orientation.z,
            pose.orientation.w,
        )
        self.odom_stamp = self._now()

    def _on_depth_info(self, msg: CameraInfo) -> None:
        self.depth_intrinsics = (msg.k[0], msg.k[4], msg.k[2], msg.k[5])

    def _enable_sensor_subscriptions(self) -> None:
        if self.scan_subscription is None:
            self.scan_subscription = self.create_subscription(
                LaserScan, self.scan_topic, self._on_scan, self.sensor_qos
            )
        if self.door_scan_subscription is None:
            self.door_scan_subscription = self.create_subscription(
                LaserScan, self.door_scan_topic, self._on_door_scan, self.sensor_qos
            )
        if self.odom_subscription is None:
            self.odom_subscription = self.create_subscription(
                Odometry, "/odometry/filtered", self._on_odom, 20
            )
        if self.door_status_source == "geometry" and self.depth_info_subscription is None:
            self.depth_info_subscription = self.create_subscription(
                CameraInfo,
                self.depth_info_topic,
                self._on_depth_info,
                self.sensor_qos,
            )
        if self.depth_subscription is None and self.door_status_source == "geometry":
            self.depth_subscription = self.create_subscription(
                Image,
                self.depth_topic,
                self._on_depth_image,
                self.sensor_qos,
            )

    def _disable_sensor_subscriptions(self) -> None:
        for attribute in (
            "scan_subscription",
            "door_scan_subscription",
            "odom_subscription",
            "depth_info_subscription",
            "depth_subscription",
        ):
            subscription = getattr(self, attribute)
            if subscription is not None:
                self.destroy_subscription(subscription)
                setattr(self, attribute, None)

    def _on_depth_image(self, msg: Image) -> None:
        # Depth geometry is only needed while an entry attempt is active.  Keeping
        # this callback hot in IDLE used a full image conversion and two geometry
        # passes at 5 Hz even when the robot was doing ordinary navigation.
        if self.state in (EntryState.IDLE, EntryState.COMPLETE, EntryState.FAILED):
            return
        now = self._now()
        if now - self.last_depth_processed < self.depth_process_period:
            return
        if self.depth_intrinsics is None:
            return
        if msg.encoding in {"16UC1", "mono16"}:
            dtype = ">u2" if msg.is_bigendian else "<u2"
            depth = np.frombuffer(msg.data, dtype=dtype)
            depth = depth.reshape(msg.height, msg.step // 2)[:, : msg.width]
            depth_m = depth.astype(np.float32) * self.depth_scale
        elif msg.encoding == "32FC1":
            dtype = ">f4" if msg.is_bigendian else "<f4"
            depth = np.frombuffer(msg.data, dtype=dtype)
            depth_m = depth.reshape(msg.height, msg.step // 4)[:, : msg.width]
        else:
            return
        fx, fy, cx, cy = self.depth_intrinsics
        self.cabin_floor_points = count_cabin_floor_points(
            depth_m,
            fx=fx,
            fy=fy,
            cx=cx,
            cy=cy,
            camera_forward_offset=self.camera_forward_offset,
            camera_height=self.camera_height,
            min_x=self.floor_min_x,
            max_x=self.floor_max_x,
            half_width=self.floor_half_width,
            z_tolerance=self.floor_z_tolerance,
        )
        self.cabin_floor_present = self.cabin_floor_points >= self.floor_min_points
        (
            self.depth_opening_present,
            self.door_center_valid_points,
            self.door_center_median_depth,
        ) = detect_depth_opening(
            depth_m,
            cx=cx,
            center_half_fraction=self.door_center_half_fraction,
            top_fraction=self.door_center_top_fraction,
            bottom_fraction=self.door_center_bottom_fraction,
            min_depth=self.door_open_min_depth,
            min_valid_points=self.door_open_min_valid_points,
        )
        self.depth_stamp = now
        self.last_depth_processed = now

    def _on_start(self, _request, response):
        if self.state in (EntryState.IDLE, EntryState.COMPLETE, EntryState.FAILED):
            self._begin("manual_start")
        return response

    def _on_cancel(self, _request, response):
        self._cancel_nav2_goals()
        self._stop()
        self._set_state(EntryState.IDLE, "cancelled")
        return response

    def _begin(self, reason: str) -> None:
        self._cancel_nav2_goals()
        self._enable_sensor_subscriptions()
        self.control_timer.reset()
        self.start_xy = None
        self.target_yaw = None
        self.entry_started = 0.0
        self.blocked_started = 0.0
        self.geometry_open_started = 0.0
        self.geometry_door_open = False
        self.last_path_request = 0.0
        self.path_valid_count = 0
        self.nav_started = 0.0
        self._set_state(EntryState.WAIT_SAFE, reason)

    def _set_state(self, state: EntryState, reason: str = "") -> None:
        self.state = state
        self.state_started = self._now()
        if state in (EntryState.IDLE, EntryState.COMPLETE, EntryState.FAILED):
            self.control_timer.cancel()
            self._disable_sensor_subscriptions()
        self._publish_status(reason)

    def _publish_status(self, reason: str = "") -> None:
        geometry_mode = self.door_status_source == "geometry"
        lidar_mode = self.door_status_source == "lidar"
        depth_fresh = self._fresh(self.depth_stamp)
        geometry_open_evidence = (
            self.cabin_floor_present or self.depth_opening_present
        )
        if lidar_mode:
            elevator_safe = (
                self.geometry_door_open
                and self._fresh(self.door_scan_stamp)
                and self._door_open_candidate()
            )
        elif geometry_mode:
            elevator_safe = (
                self.geometry_door_open and geometry_open_evidence and depth_fresh
            )
        else:
            elevator_safe = self.elevator.safe_to_enter
        if self.entry_mode == "nav2":
            elevator_safe = (
                self.path_valid_count >= self.nav_path_confirm_count
                or self.state in (EntryState.NAVIGATING, EntryState.COMPLETE)
            )
        payload = {
            "state": self.state.value,
            "reason": reason,
            "entry_mode": self.entry_mode,
            "door_status_source": self.door_status_source,
            "elevator_safe": elevator_safe,
            "scan_fresh": self._fresh(self.scan_stamp),
            "door_scan_fresh": self._fresh(self.door_scan_stamp),
            "lidar_door_open_candidate": self._lidar_door_open_candidate(),
            "odom_fresh": self._fresh(self.odom_stamp),
            "depth_fresh": depth_fresh,
            "cabin_floor_present": self.cabin_floor_present,
            "cabin_floor_points": self.cabin_floor_points,
            "depth_opening_present": self.depth_opening_present,
            "door_center_valid_points": self.door_center_valid_points,
            "door_center_median_depth": round(self.door_center_median_depth, 3),
            "nav_path_valid_count": self.path_valid_count,
            "nav_goal_active": self.state == EntryState.NAVIGATING,
        }
        self.status_pub.publish(String(data=json.dumps(payload, ensure_ascii=True)))

    def _fail(self, reason: str) -> None:
        self._cancel_nav2_goals()
        self._stop()
        self.failure_pub.publish(String(data=reason))
        self._set_state(EntryState.FAILED, reason)
        self.get_logger().error(f"Elevator entry failed: {reason}")

    def _stop(self) -> None:
        self.cmd_pub.publish(Twist())

    def _nav_pose(self) -> PoseStamped:
        pose = PoseStamped()
        pose.header.frame_id = "map"
        pose.header.stamp = self.get_clock().now().to_msg()
        pose.pose.position.x = self.nav_goal_x
        pose.pose.position.y = self.nav_goal_y
        pose.pose.orientation.z = math.sin(self.nav_goal_yaw * 0.5)
        pose.pose.orientation.w = math.cos(self.nav_goal_yaw * 0.5)
        return pose

    def _cancel_nav2_goals(self) -> None:
        if self.path_goal_handle is not None:
            self.path_goal_handle.cancel_goal_async()
        if self.nav_goal_handle is not None:
            self.nav_goal_handle.cancel_goal_async()
        self.path_send_future = None
        self.path_goal_handle = None
        self.path_result_future = None
        self.nav_send_future = None
        self.nav_goal_handle = None
        self.nav_result_future = None

    def _request_path(self, now: float) -> None:
        if not self.path_client.server_is_ready():
            return
        goal = ComputePathToPose.Goal()
        goal.goal = self._nav_pose()
        goal.use_start = False
        self.path_send_future = self.path_client.send_goal_async(goal)
        self.last_path_request = now

    def _start_nav2_navigation(self, now: float) -> None:
        if not self.nav_client.server_is_ready():
            self.path_valid_count = 0
            self._publish_status("navigate_action_unavailable")
            return
        goal = NavigateToPose.Goal()
        goal.pose = self._nav_pose()
        self.nav_send_future = self.nav_client.send_goal_async(goal)
        self.nav_started = now
        self._set_state(EntryState.NAVIGATING, "door_path_confirmed")

    def _tick_nav2(self) -> None:
        now = self._now()

        if self.state == EntryState.WAIT_SAFE:
            if self.path_send_future is not None and self.path_send_future.done():
                try:
                    handle = self.path_send_future.result()
                except Exception as exc:
                    self.get_logger().warning(f"Path request failed: {exc}")
                    handle = None
                self.path_send_future = None
                if handle is not None and handle.accepted:
                    self.path_goal_handle = handle
                    self.path_result_future = handle.get_result_async()
                else:
                    self.path_valid_count = 0

            if self.path_result_future is not None and self.path_result_future.done():
                try:
                    wrapped = self.path_result_future.result()
                    pose_count = len(wrapped.result.path.poses)
                    valid = nav2_path_is_valid(wrapped.status, pose_count)
                except Exception as exc:
                    self.get_logger().warning(f"Path result failed: {exc}")
                    valid = False
                self.path_goal_handle = None
                self.path_result_future = None
                self.path_valid_count = self.path_valid_count + 1 if valid else 0
                self._publish_status(
                    "door_path_open" if valid else "waiting_for_door_path"
                )
                if self.path_valid_count >= self.nav_path_confirm_count:
                    self._start_nav2_navigation(now)
                    return

            path_idle = (
                self.path_send_future is None and self.path_result_future is None
            )
            if path_idle and now - self.last_path_request >= self.nav_path_check_period:
                self._request_path(now)
            return

        if self.state != EntryState.NAVIGATING:
            return
        if now - self.nav_started > self.nav_navigation_timeout:
            self._fail("nav2_navigation_timeout")
            return
        if self.nav_send_future is not None and self.nav_send_future.done():
            try:
                handle = self.nav_send_future.result()
            except Exception as exc:
                self._fail(f"nav2_goal_request_failed:{exc}")
                return
            self.nav_send_future = None
            if not handle.accepted:
                self._fail("nav2_goal_rejected")
                return
            self.nav_goal_handle = handle
            self.nav_result_future = handle.get_result_async()
            self._publish_status("nav2_goal_accepted")
        if self.nav_result_future is not None and self.nav_result_future.done():
            try:
                status = self.nav_result_future.result().status
            except Exception as exc:
                self._fail(f"nav2_navigation_result_failed:{exc}")
                return
            self.nav_goal_handle = None
            self.nav_result_future = None
            if status == GoalStatus.STATUS_SUCCEEDED:
                self.entered_pub.publish(Empty())
                self._set_state(EntryState.COMPLETE, "nav2_entered_confirmed")
            else:
                self._fail(f"nav2_navigation_failed:{status}")

    def _clear(self) -> bool:
        return (
            self.scan is not None
            and self._fresh(self.scan_stamp)
            and corridor_is_clear(
                self.scan,
                self.clearance_distance,
                self.corridor_half_width,
                min_blocking_points=self.min_blocking_points,
            )
        )

    def _distance(self) -> float:
        if self.start_xy is None or self.odom_xy is None:
            return 0.0
        return math.hypot(
            self.odom_xy[0] - self.start_xy[0],
            self.odom_xy[1] - self.start_xy[1],
        )

    def _lidar_door_open_candidate(self) -> bool:
        return (
            self.door_scan is not None
            and self._fresh(self.door_scan_stamp)
            and lidar_door_is_open(
                self.door_scan,
                check_distance=self.door_check_distance,
                half_width=self.door_half_width,
                min_blocking_points=self.door_min_blocking_points,
            )
        )

    def _door_open_candidate(self) -> bool:
        if self.door_status_source == "lidar":
            return self._lidar_door_open_candidate()
        return (
            self._fresh(self.depth_stamp)
            and (self.cabin_floor_present or self.depth_opening_present)
        )

    def _update_geometry_door(self, now: float) -> bool:
        geometry_candidate = (
            self._fresh(self.scan_stamp)
            and self._clear()
            and self._door_open_candidate()
        )
        if not geometry_candidate:
            self.geometry_open_started = 0.0
            self.geometry_door_open = False
            return False
        if self.geometry_open_started <= 0.0:
            self.geometry_open_started = now
        self.geometry_door_open = (
            now - self.geometry_open_started >= self.door_open_confirm_duration
        )
        return self.geometry_door_open

    def _tick(self) -> None:
        if self.state in (EntryState.IDLE, EntryState.COMPLETE, EntryState.FAILED):
            return

        if self.entry_mode == "nav2":
            self._tick_nav2()
            return

        geometry_mode = self.door_status_source == "geometry"
        lidar_mode = self.door_status_source == "lidar"
        sensor_mode = geometry_mode or lidar_mode
        if not sensor_mode:
            if not self._fresh(self.elevator_stamp):
                self._fail("elevator_status_stale")
                return
            if not self.elevator.safe_to_enter:
                self._fail("elevator_became_unsafe")
                return
        if not self._fresh(self.scan_stamp):
            if sensor_mode and self.state == EntryState.WAIT_SAFE:
                self.geometry_open_started = 0.0
                return
            self._fail("scan_stale")
            return
        if not self._fresh(self.odom_stamp) or self.odom_xy is None or self.odom_yaw is None:
            if sensor_mode and self.state == EntryState.WAIT_SAFE:
                return
            self._fail("odometry_stale")
            return
        if geometry_mode and not self._fresh(self.depth_stamp):
            if self.state == EntryState.WAIT_SAFE:
                self.geometry_open_started = 0.0
                return
            self._fail("depth_stale")
            return
        if lidar_mode and not self._fresh(self.door_scan_stamp):
            if self.state == EntryState.WAIT_SAFE:
                self.geometry_open_started = 0.0
                return
            self._fail("door_scan_stale")
            return

        now = self._now()
        if self.state == EntryState.WAIT_SAFE:
            ready = self._update_geometry_door(now) if sensor_mode else self._clear()
            if ready:
                self.target_yaw = self.odom_yaw
                self._set_state(EntryState.ALIGN, "entry_corridor_clear")
            return

        if self.state == EntryState.ALIGN:
            self._stop()
            if sensor_mode and not (
                self._clear() and self._door_open_candidate()
            ):
                self.geometry_open_started = 0.0
                self.geometry_door_open = False
                self._set_state(EntryState.WAIT_SAFE, "door_closed_again")
                return
            if now - self.state_started >= self.align_duration:
                self.start_xy = self.odom_xy
                self.entry_started = now
                self._set_state(EntryState.ENTER, "aligned")
            return

        if self.state == EntryState.ENTER:
            if now - self.entry_started > self.entry_timeout:
                self._fail("entry_timeout")
                return
            if not self._clear():
                self._stop()
                self.blocked_started = now
                self._set_state(EntryState.BLOCKED, "entry_corridor_blocked")
                return
            if self._distance() >= self.entry_distance:
                self._stop()
                self._set_state(EntryState.VERIFY, "entry_distance_reached")
                return
            cmd = Twist()
            cmd.linear.x = self.entry_speed
            if self.target_yaw is not None:
                error = normalize_angle(self.target_yaw - self.odom_yaw)
                cmd.angular.z = max(
                    -self.max_angular_speed,
                    min(self.max_angular_speed, self.heading_kp * error),
                )
            self.cmd_pub.publish(cmd)
            return

        if self.state == EntryState.BLOCKED:
            self._stop()
            if self._clear():
                self._set_state(EntryState.ENTER, "corridor_clear_again")
            elif now - self.blocked_started >= self.blocked_timeout:
                self._fail("blocked_timeout")
            return

        if self.state == EntryState.VERIFY:
            self._stop()
            if now - self.state_started >= self.verify_duration:
                self.entered_pub.publish(Empty())
                self._set_state(EntryState.COMPLETE, "entered_confirmed")


def main(args=None) -> None:
    rclpy.init(args=args)
    node = ElevatorEntryController()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node._stop()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
