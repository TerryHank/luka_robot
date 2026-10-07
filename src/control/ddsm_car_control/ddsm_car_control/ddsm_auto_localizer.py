#!/usr/bin/env python3
import copy
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Union

import rclpy
from geometry_msgs.msg import PoseWithCovarianceStamped, Twist
from nav_msgs.msg import OccupancyGrid
from rclpy.node import Node
from rclpy.qos import QoSDurabilityPolicy, QoSProfile, QoSReliabilityPolicy
from rclpy.time import Time
from sensor_msgs.msg import LaserScan
from std_msgs.msg import Bool, String
from std_srvs.srv import Empty
from tf2_ros import Buffer, TransformException, TransformListener

from ddsm_car_control.ddsm_home_manager import (
    compute_map_identity,
    normalize_angle,
    yaw_from_quaternion,
    yaw_to_quaternion,
)


PathLike = Union[str, Path]


@dataclass
class SavedLocalizationPose:
    configured: bool
    frame_id: str
    x: float
    y: float
    yaw: float
    map_file: str = ""
    map_sha256: str = ""


def _read_yaml(path: Path) -> dict:
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} does not contain a YAML mapping")
    return data


def load_saved_pose(path: PathLike) -> SavedLocalizationPose:
    data = _read_yaml(Path(path).expanduser())
    return SavedLocalizationPose(
        configured=bool(data.get("configured", True)),
        frame_id=str(data.get("frame_id", "map")),
        x=float(data.get("x", 0.0)),
        y=float(data.get("y", 0.0)),
        yaw=normalize_angle(float(data.get("yaw", 0.0))),
        map_file=str(data.get("map_file", "")),
        map_sha256=str(data.get("map_sha256", "")),
    )


def dump_saved_pose(
    path: PathLike,
    pose: SavedLocalizationPose,
    current_map_file: PathLike = "",
) -> None:
    import yaml

    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    map_file = str(current_map_file or pose.map_file)
    map_sha256 = pose.map_sha256
    if map_file:
        map_sha256 = compute_map_identity(map_file)
    data = {
        "configured": bool(pose.configured),
        "frame_id": pose.frame_id,
        "x": float(pose.x),
        "y": float(pose.y),
        "yaw": float(normalize_angle(pose.yaw)),
        "map_file": map_file,
        "map_sha256": map_sha256,
    }
    target.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def map_identity_matches(
    pose: SavedLocalizationPose,
    current_map_file: PathLike,
) -> bool:
    if not pose.configured:
        return False
    current_path = Path(current_map_file).expanduser()
    if pose.map_sha256:
        try:
            return compute_map_identity(current_path) == pose.map_sha256
        except OSError:
            return False
    if not pose.map_file:
        return True
    return Path(pose.map_file).expanduser() == current_path


def make_initial_pose(
    pose: SavedLocalizationPose,
    xy_std: float,
    yaw_std: float,
) -> PoseWithCovarianceStamped:
    msg = PoseWithCovarianceStamped()
    msg.header.frame_id = pose.frame_id
    msg.pose.pose.position.x = pose.x
    msg.pose.pose.position.y = pose.y
    msg.pose.pose.position.z = 0.0
    msg.pose.pose.orientation = yaw_to_quaternion(pose.yaw)
    msg.pose.covariance[0] = xy_std * xy_std
    msg.pose.covariance[7] = xy_std * xy_std
    msg.pose.covariance[35] = yaw_std * yaw_std
    return msg


def make_initial_pose_qos() -> QoSProfile:
    return QoSProfile(
        depth=10,
        durability=QoSDurabilityPolicy.TRANSIENT_LOCAL,
        reliability=QoSReliabilityPolicy.RELIABLE,
    )


def use_latest_tf_for_initial_pose(
    msg: PoseWithCovarianceStamped,
) -> PoseWithCovarianceStamped:
    prepared = copy.deepcopy(msg)
    prepared.header.stamp.sec = 0
    prepared.header.stamp.nanosec = 0
    return prepared


def warm_start_should_timeout(
    *,
    amcl_pose_seen: bool,
    elapsed_seconds: float,
    warm_start_timeout: float,
) -> bool:
    return bool(amcl_pose_seen and elapsed_seconds >= warm_start_timeout)


def covariance_is_converged(
    covariance: Iterable[float],
    xy_std_threshold: float,
    yaw_std_threshold: float,
) -> bool:
    values = list(covariance)
    if len(values) < 36:
        return False
    xy_var = xy_std_threshold * xy_std_threshold
    yaw_var = yaw_std_threshold * yaw_std_threshold
    return values[0] <= xy_var and values[7] <= xy_var and values[35] <= yaw_var


def scan_to_map_match_score(
    occupancy_grid: OccupancyGrid,
    scan: LaserScan,
    *,
    base_x: float,
    base_y: float,
    base_yaw: float,
    laser_x: float,
    laser_y: float,
    laser_yaw: float,
    hit_distance: float,
    max_points: int,
    min_points: int,
) -> tuple[float, int]:
    """Return the fraction of scan endpoints near occupied map cells."""
    info = occupancy_grid.info
    if (
        info.resolution <= 0.0
        or info.width <= 0
        or info.height <= 0
        or not occupancy_grid.data
        or not scan.ranges
    ):
        return 0.0, 0

    base_cos = math.cos(base_yaw)
    base_sin = math.sin(base_yaw)
    laser_map_x = base_x + base_cos * laser_x - base_sin * laser_y
    laser_map_y = base_y + base_sin * laser_x + base_cos * laser_y
    laser_map_yaw = normalize_angle(base_yaw + laser_yaw)

    origin = info.origin
    origin_yaw = yaw_from_quaternion(origin.orientation)
    origin_cos = math.cos(origin_yaw)
    origin_sin = math.sin(origin_yaw)
    search_cells = max(0, int(math.ceil(hit_distance / info.resolution)))
    stride = max(1, int(math.ceil(len(scan.ranges) / max(1, max_points))))

    hits = 0
    considered = 0
    for index in range(0, len(scan.ranges), stride):
        distance = scan.ranges[index]
        if (
            not math.isfinite(distance)
            or distance < scan.range_min
            or distance > scan.range_max
        ):
            continue

        angle = laser_map_yaw + scan.angle_min + index * scan.angle_increment
        endpoint_x = laser_map_x + distance * math.cos(angle)
        endpoint_y = laser_map_y + distance * math.sin(angle)
        dx = endpoint_x - origin.position.x
        dy = endpoint_y - origin.position.y
        grid_x = int(math.floor((origin_cos * dx + origin_sin * dy) / info.resolution))
        grid_y = int(math.floor((-origin_sin * dx + origin_cos * dy) / info.resolution))
        if not (0 <= grid_x < info.width and 0 <= grid_y < info.height):
            continue

        considered += 1
        matched = False
        for offset_y in range(-search_cells, search_cells + 1):
            test_y = grid_y + offset_y
            if not 0 <= test_y < info.height:
                continue
            for offset_x in range(-search_cells, search_cells + 1):
                if offset_x * offset_x + offset_y * offset_y > search_cells * search_cells:
                    continue
                test_x = grid_x + offset_x
                if not 0 <= test_x < info.width:
                    continue
                if occupancy_grid.data[test_y * info.width + test_x] >= 65:
                    matched = True
                    break
            if matched:
                break
        if matched:
            hits += 1

    if considered < min_points:
        return 0.0, considered
    return hits / considered, considered


def scan_has_rotation_clearance(scan: LaserScan, min_clearance: float) -> bool:
    valid_ranges = []
    for distance in scan.ranges:
        if not math.isfinite(distance):
            continue
        if distance < scan.range_min or distance > scan.range_max:
            continue
        valid_ranges.append(distance)
        if distance < min_clearance:
            return False
    return bool(valid_ranges)


def _sector_min_range(scan: LaserScan, start_angle: float, end_angle: float) -> float:
    values = []
    for index, distance in enumerate(scan.ranges):
        if not math.isfinite(distance):
            continue
        if distance < scan.range_min or distance > scan.range_max:
            continue
        angle = normalize_angle(scan.angle_min + index * scan.angle_increment)
        if start_angle <= end_angle:
            in_sector = start_angle <= angle <= end_angle
        else:
            in_sector = angle >= start_angle or angle <= end_angle
        if in_sector:
            values.append(distance)
    if not values:
        return 0.0
    return min(values)


def choose_escape_twist_from_scan(
    scan: LaserScan,
    speed: float,
    min_clearance: float,
    lateral_direction: float = 1.0,
) -> Twist | None:
    left_clearance = _sector_min_range(scan, math.radians(60.0), math.radians(120.0))
    right_clearance = _sector_min_range(scan, math.radians(-120.0), math.radians(-60.0))
    back_clearance = _sector_min_range(scan, math.radians(150.0), math.radians(-150.0))

    twist = Twist()
    if left_clearance >= min_clearance or right_clearance >= min_clearance:
        direction = 1.0 if lateral_direction >= 0.0 else -1.0
        twist.linear.y = direction * (speed if left_clearance >= right_clearance else -speed)
        return twist
    if back_clearance >= min_clearance:
        twist.linear.x = -speed
        return twist
    return None


def saved_pose_from_amcl(
    msg: PoseWithCovarianceStamped,
    current_map_file: PathLike,
) -> SavedLocalizationPose:
    yaw = yaw_from_quaternion(msg.pose.pose.orientation)
    map_file = str(current_map_file)
    map_sha256 = ""
    if map_file:
        map_sha256 = compute_map_identity(map_file)
    return SavedLocalizationPose(
        configured=True,
        frame_id=msg.header.frame_id or "map",
        x=float(msg.pose.pose.position.x),
        y=float(msg.pose.pose.position.y),
        yaw=yaw,
        map_file=map_file,
        map_sha256=map_sha256,
    )


class DDSMAutoLocalizer(Node):
    def __init__(self) -> None:
        super().__init__("ddsm_auto_localizer")

        self.declare_parameter("map_file", "/home/sunrise/luka_ws/map/maps/ddsm_map.yaml")
        self.declare_parameter(
            "last_pose_file",
            "/home/sunrise/luka_ws/common/config/last_amcl_pose.yaml",
        )
        self.declare_parameter("map_frame", "map")
        self.declare_parameter("base_frame", "base_link")
        self.declare_parameter("map_topic", "/map")
        self.declare_parameter("initial_pose_topic", "/initialpose")
        self.declare_parameter("amcl_pose_topic", "/amcl_pose")
        self.declare_parameter("scan_topic", "/scan")
        self.declare_parameter("cmd_vel_topic", "/cmd_vel_nav")
        self.declare_parameter("status_topic", "/localization/status")
        self.declare_parameter("ready_topic", "/localization/ready")
        self.declare_parameter("hot_switch_topic", "/localization/hot_switch")
        self.declare_parameter(
            "global_localization_service",
            "/reinitialize_global_localization",
        )
        self.declare_parameter("nomotion_update_service", "/request_nomotion_update")
        self.declare_parameter("check_period", 0.5)
        self.declare_parameter("save_period", 3.0)
        self.declare_parameter("warm_start_timeout", 20.0)
        self.declare_parameter("global_localization_timeout", 60.0)
        self.declare_parameter("warm_start_scan_reject_timeout", 6.0)
        self.declare_parameter("global_localization_retry_period", 8.0)
        self.declare_parameter("initial_pose_republish_period", 2.0)
        self.declare_parameter("enable_rotation", True)
        self.declare_parameter("max_rotation_speed", 0.22)
        self.declare_parameter("rotation_clearance", 0.45)
        self.declare_parameter("enable_escape", True)
        self.declare_parameter("escape_speed", 0.08)
        self.declare_parameter("escape_lateral_direction", 1.0)
        self.declare_parameter("escape_duration", 1.5)
        self.declare_parameter("escape_max_attempts", 3)
        self.declare_parameter("initial_xy_std", 0.25)
        self.declare_parameter("initial_yaw_std", 0.35)
        self.declare_parameter("xy_std_threshold", 0.20)
        self.declare_parameter("yaw_std_threshold", 0.25)
        self.declare_parameter("stable_samples_required", 5)
        self.declare_parameter("scan_match_required", True)
        self.declare_parameter("scan_match_min_score", 0.40)
        self.declare_parameter("scan_match_hit_distance", 0.10)
        self.declare_parameter("scan_match_max_points", 180)
        self.declare_parameter("scan_match_min_points", 30)

        self.map_file = Path(str(self.get_parameter("map_file").value)).expanduser()
        self.last_pose_file = Path(
            str(self.get_parameter("last_pose_file").value)
        ).expanduser()
        self.map_frame = str(self.get_parameter("map_frame").value)
        self.base_frame = str(self.get_parameter("base_frame").value)
        self.check_period = float(self.get_parameter("check_period").value)
        self.save_period = float(self.get_parameter("save_period").value)
        self.warm_start_timeout = float(
            self.get_parameter("warm_start_timeout").value
        )
        self.global_timeout = float(
            self.get_parameter("global_localization_timeout").value
        )
        self.warm_start_scan_reject_timeout = float(
            self.get_parameter("warm_start_scan_reject_timeout").value
        )
        self.global_localization_retry_period = float(
            self.get_parameter("global_localization_retry_period").value
        )
        self.initial_pose_republish_period = float(
            self.get_parameter("initial_pose_republish_period").value
        )
        self.enable_rotation = bool(self.get_parameter("enable_rotation").value)
        self.max_rotation_speed = float(self.get_parameter("max_rotation_speed").value)
        self.rotation_clearance = float(self.get_parameter("rotation_clearance").value)
        self.enable_escape = bool(self.get_parameter("enable_escape").value)
        self.escape_speed = float(self.get_parameter("escape_speed").value)
        self.escape_lateral_direction = float(
            self.get_parameter("escape_lateral_direction").value
        )
        self.escape_duration = float(self.get_parameter("escape_duration").value)
        self.escape_max_attempts = int(self.get_parameter("escape_max_attempts").value)
        self.initial_xy_std = float(self.get_parameter("initial_xy_std").value)
        self.initial_yaw_std = float(self.get_parameter("initial_yaw_std").value)
        self.xy_std_threshold = float(self.get_parameter("xy_std_threshold").value)
        self.yaw_std_threshold = float(self.get_parameter("yaw_std_threshold").value)
        self.stable_samples_required = int(
            self.get_parameter("stable_samples_required").value
        )
        self.scan_match_required = bool(
            self.get_parameter("scan_match_required").value
        )
        self.scan_match_min_score = float(
            self.get_parameter("scan_match_min_score").value
        )
        self.scan_match_hit_distance = float(
            self.get_parameter("scan_match_hit_distance").value
        )
        self.scan_match_max_points = int(
            self.get_parameter("scan_match_max_points").value
        )
        self.scan_match_min_points = int(
            self.get_parameter("scan_match_min_points").value
        )

        self.state = "starting"
        self.localized = False
        self.stable_samples = 0
        self.latest_scan = None
        self.latest_map = None
        self.latest_scan_match_score = 0.0
        self.latest_scan_match_points = 0
        self.last_scan_match_log_at = self.get_clock().now()
        self.warm_start_pose = None
        self.amcl_pose_seen = False
        self.global_localization_called = False
        self.last_global_localization_at = self.get_clock().now()
        self.escape_attempts = 0
        self.escape_started_at = None
        self.escape_twist = None
        self.state_started_at = self.get_clock().now()
        self.last_save_at = self.get_clock().now()
        self.last_initial_pose_at = self.get_clock().now()
        self.last_nomotion_update_at = self.get_clock().now()
        self.service_futures = []
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)

        self.initial_pose_pub = self.create_publisher(
            PoseWithCovarianceStamped,
            str(self.get_parameter("initial_pose_topic").value),
            make_initial_pose_qos(),
        )
        self.cmd_vel_pub = self.create_publisher(
            Twist,
            str(self.get_parameter("cmd_vel_topic").value),
            10,
        )
        self.status_pub = self.create_publisher(
            String,
            str(self.get_parameter("status_topic").value),
            10,
        )
        self.ready_pub = self.create_publisher(
            Bool,
            str(self.get_parameter("ready_topic").value),
            10,
        )
        self.global_localization_client = self.create_client(
            Empty,
            str(self.get_parameter("global_localization_service").value),
        )
        self.nomotion_update_client = self.create_client(
            Empty,
            str(self.get_parameter("nomotion_update_service").value),
        )
        self.create_subscription(
            OccupancyGrid,
            str(self.get_parameter("map_topic").value),
            self.on_map,
            QoSProfile(
                depth=1,
                durability=QoSDurabilityPolicy.TRANSIENT_LOCAL,
                reliability=QoSReliabilityPolicy.RELIABLE,
            ),
        )
        self.create_subscription(
            PoseWithCovarianceStamped,
            str(self.get_parameter("amcl_pose_topic").value),
            self.on_amcl_pose,
            10,
        )
        self.create_subscription(
            LaserScan,
            str(self.get_parameter("scan_topic").value),
            self.on_scan,
            10,
        )
        self.create_subscription(
            String,
            str(self.get_parameter("hot_switch_topic").value),
            self.on_hot_switch,
            QoSProfile(
                depth=1,
                durability=QoSDurabilityPolicy.TRANSIENT_LOCAL,
                reliability=QoSReliabilityPolicy.RELIABLE,
            ),
        )
        self.create_timer(self.check_period, self.on_timer)

        self.publish_status("starting")
        self.publish_ready(False)
        self.get_logger().info(
            "AMCL auto localizer ready | "
            f"map_file={self.map_file} last_pose_file={self.last_pose_file} "
            f"enable_rotation={self.enable_rotation} "
            f"scan_match_min_score={self.scan_match_min_score:.2f}"
        )

    def seconds_since(self, start_time) -> float:
        return (self.get_clock().now() - start_time).nanoseconds / 1e9

    def publish_status(self, status: str) -> None:
        msg = String()
        msg.data = status
        self.status_pub.publish(msg)

    def publish_ready(self, ready: bool) -> None:
        msg = Bool()
        msg.data = bool(ready)
        self.ready_pub.publish(msg)

    def set_state(self, state: str) -> None:
        if state != self.state:
            self.get_logger().info(f"localization status: {state}")
        self.state = state
        self.state_started_at = self.get_clock().now()
        self.publish_status(state)

    def on_scan(self, msg: LaserScan) -> None:
        self.latest_scan = msg

    def on_map(self, msg: OccupancyGrid) -> None:
        self.latest_map = msg

    def on_hot_switch(self, msg: String) -> None:
        try:
            command = json.loads(msg.data)
            map_file = str(command["map_file"])
            last_pose_file = str(command["last_pose_file"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            self.get_logger().error(f"invalid localization hot-switch command: {exc}")
            return
        self.map_file = Path(map_file).expanduser()
        self.last_pose_file = Path(last_pose_file).expanduser()
        self.localized = False
        self.stable_samples = 0
        self.latest_map = None
        self.latest_scan_match_score = 0.0
        self.latest_scan_match_points = 0
        self.warm_start_pose = None
        self.amcl_pose_seen = False
        self.global_localization_called = False
        self.escape_attempts = 0
        self.escape_started_at = None
        self.escape_twist = None
        self.stop_rotation()
        self.set_state("hot_switch_ready")
        self.publish_ready(False)
        self.get_logger().info(
            f"ready for hot map switch: map_file={self.map_file} "
            f"last_pose_file={self.last_pose_file}"
        )

    def current_scan_match(self, msg: PoseWithCovarianceStamped) -> tuple[float, int]:
        if self.latest_map is None or self.latest_scan is None:
            return 0.0, 0
        try:
            transform = self.tf_buffer.lookup_transform(
                self.base_frame,
                self.latest_scan.header.frame_id,
                Time(),
            )
        except TransformException:
            return 0.0, 0

        translation = transform.transform.translation
        laser_yaw = yaw_from_quaternion(transform.transform.rotation)
        pose = msg.pose.pose
        return scan_to_map_match_score(
            self.latest_map,
            self.latest_scan,
            base_x=float(pose.position.x),
            base_y=float(pose.position.y),
            base_yaw=yaw_from_quaternion(pose.orientation),
            laser_x=float(translation.x),
            laser_y=float(translation.y),
            laser_yaw=laser_yaw,
            hit_distance=self.scan_match_hit_distance,
            max_points=self.scan_match_max_points,
            min_points=self.scan_match_min_points,
        )

    def on_amcl_pose(self, msg: PoseWithCovarianceStamped) -> None:
        self.amcl_pose_seen = True
        converged = covariance_is_converged(
            msg.pose.covariance,
            self.xy_std_threshold,
            self.yaw_std_threshold,
        )
        score, points = self.current_scan_match(msg)
        self.latest_scan_match_score = score
        self.latest_scan_match_points = points
        scan_matches = (
            not self.scan_match_required
            or (
                points >= self.scan_match_min_points
                and score >= self.scan_match_min_score
            )
        )
        if converged and scan_matches:
            self.stable_samples += 1
        else:
            self.stable_samples = 0
            if (
                converged
                and self.scan_match_required
                and self.seconds_since(self.last_scan_match_log_at) >= 2.0
            ):
                self.get_logger().warn(
                    "rejecting low-covariance AMCL pose because scan does not match map "
                    f"score={score:.3f} points={points} "
                    f"required_score={self.scan_match_min_score:.3f}"
                )
                self.last_scan_match_log_at = self.get_clock().now()

        if self.stable_samples >= self.stable_samples_required:
            if not self.localized:
                self.localized = True
                self.stop_rotation()
                self.set_state("localized")
                self.publish_ready(True)
                self.get_logger().info(
                    "AMCL covariance and scan-map match are stable; navigation may start "
                    f"score={score:.3f} points={points}"
                )
            self.save_pose_if_due(msg)
        else:
            self.publish_ready(False)

    def save_pose_if_due(self, msg: PoseWithCovarianceStamped) -> None:
        if self.seconds_since(self.last_save_at) < self.save_period:
            return
        try:
            pose = saved_pose_from_amcl(msg, self.map_file)
            dump_saved_pose(self.last_pose_file, pose, self.map_file)
            self.last_save_at = self.get_clock().now()
        except OSError as exc:
            self.get_logger().warn(f"unable to save AMCL pose: {exc}")

    def load_warm_start_pose(self):
        try:
            pose = load_saved_pose(self.last_pose_file)
        except (OSError, ValueError) as exc:
            self.get_logger().info(f"no usable saved AMCL pose: {exc}")
            return None
        if pose.frame_id != self.map_frame:
            self.get_logger().warn(
                f"saved AMCL pose frame mismatch: {pose.frame_id} != {self.map_frame}"
            )
            return None
        if not map_identity_matches(pose, self.map_file):
            self.get_logger().warn("saved AMCL pose belongs to a different map")
            return None
        return pose

    def publish_initial_pose(self, pose: SavedLocalizationPose) -> None:
        msg = make_initial_pose(pose, self.initial_xy_std, self.initial_yaw_std)
        self.initial_pose_pub.publish(use_latest_tf_for_initial_pose(msg))
        self.last_initial_pose_at = self.get_clock().now()
        self.get_logger().info(
            "published saved AMCL initial pose "
            f"x={pose.x:.3f} y={pose.y:.3f} yaw={pose.yaw:.3f}"
        )

    def call_service_if_ready(self, client, service_name: str) -> bool:
        self.service_futures = [
            future for future in self.service_futures if not future.done()
        ]
        if not client.service_is_ready():
            return False
        self.service_futures.append(client.call_async(Empty.Request()))
        self.get_logger().info(f"called {service_name}")
        return True

    def start_warm_start(self) -> None:
        self.warm_start_pose = self.load_warm_start_pose()
        if self.warm_start_pose is None:
            self.start_global_localization()
            return
        self.publish_initial_pose(self.warm_start_pose)
        self.set_state("warm_start")

    def start_global_localization(self) -> None:
        self.global_localization_called = False
        self.call_global_localization_if_ready()
        self.set_state("global_localizing")

    def call_global_localization_if_ready(self) -> None:
        if (
            self.global_localization_called
            and self.seconds_since(self.last_global_localization_at)
            < self.global_localization_retry_period
        ):
            return
        if self.call_service_if_ready(
            self.global_localization_client,
            "/reinitialize_global_localization",
        ):
            self.global_localization_called = True
            self.last_global_localization_at = self.get_clock().now()

    def request_nomotion_update_if_due(self) -> None:
        if self.seconds_since(self.last_nomotion_update_at) < 1.5:
            return
        if self.call_service_if_ready(
            self.nomotion_update_client,
            "/request_nomotion_update",
        ):
            self.last_nomotion_update_at = self.get_clock().now()

    def stop_rotation(self) -> None:
        self.cmd_vel_pub.publish(Twist())

    def publish_escape_if_active(self) -> bool:
        if self.escape_twist is None or self.escape_started_at is None:
            return False
        if self.seconds_since(self.escape_started_at) >= self.escape_duration:
            self.escape_twist = None
            self.escape_started_at = None
            self.stop_rotation()
            self.request_nomotion_update_if_due()
            return False
        self.publish_status("rotation_escape")
        self.cmd_vel_pub.publish(self.escape_twist)
        return True

    def try_start_rotation_escape(self) -> bool:
        if not self.enable_escape:
            return False
        if self.escape_attempts >= self.escape_max_attempts:
            return False
        if self.latest_scan is None:
            return False
        twist = choose_escape_twist_from_scan(
            self.latest_scan,
            speed=self.escape_speed,
            min_clearance=self.rotation_clearance,
            lateral_direction=self.escape_lateral_direction,
        )
        if twist is None:
            return False
        self.escape_attempts += 1
        self.escape_twist = twist
        self.escape_started_at = self.get_clock().now()
        self.publish_status("rotation_escape")
        self.cmd_vel_pub.publish(twist)
        self.get_logger().warn(
            "rotation blocked; trying local escape "
            f"attempt={self.escape_attempts}/{self.escape_max_attempts} "
            f"vx={twist.linear.x:.3f} vy={twist.linear.y:.3f}"
        )
        return True

    def rotate_for_scan_matching(self) -> None:
        if self.publish_escape_if_active():
            return
        if not self.enable_rotation:
            self.stop_rotation()
            return
        if self.latest_scan is None:
            self.publish_status("waiting_for_scan")
            self.stop_rotation()
            return
        if not scan_has_rotation_clearance(self.latest_scan, self.rotation_clearance):
            if self.try_start_rotation_escape():
                return
            self.publish_status("rotation_blocked")
            self.stop_rotation()
            return
        twist = Twist()
        twist.angular.z = self.max_rotation_speed
        self.cmd_vel_pub.publish(twist)

    def on_timer(self) -> None:
        self.publish_status(self.state)
        self.publish_ready(self.localized)

        if self.localized:
            return
        if self.state == "starting":
            self.start_warm_start()
            return

        if self.state == "hot_switch_ready":
            self.request_nomotion_update_if_due()
            self.stop_rotation()
            return

        self.request_nomotion_update_if_due()

        if self.state == "warm_start":
            if (
                not self.amcl_pose_seen
                and self.seconds_since(self.last_initial_pose_at)
                >= self.initial_pose_republish_period
            ):
                self.publish_initial_pose(self.warm_start_pose)
            if (
                self.amcl_pose_seen
                and self.scan_match_required
                and self.latest_scan_match_points >= self.scan_match_min_points
                and self.latest_scan_match_score < self.scan_match_min_score
                and self.seconds_since(self.state_started_at)
                >= self.warm_start_scan_reject_timeout
            ):
                self.get_logger().warn(
                    "warm start pose is converged but scan does not match map; "
                    "switching to global localization early"
                )
                self.start_global_localization()
                return
            if warm_start_should_timeout(
                amcl_pose_seen=self.amcl_pose_seen,
                elapsed_seconds=self.seconds_since(self.state_started_at),
                warm_start_timeout=self.warm_start_timeout,
            ):
                self.get_logger().warn("warm start timed out; switching to global localization")
                self.start_global_localization()
                return
        elif self.state == "global_localizing":
            if self.global_localization_client.service_is_ready():
                self.call_global_localization_if_ready()
            else:
                self.publish_status("waiting_for_amcl_global_service")
            if self.seconds_since(self.state_started_at) >= self.global_timeout:
                self.stop_rotation()
                self.set_state("failed")
                self.publish_ready(False)
                self.get_logger().error("AMCL auto localization timed out")
                return
        elif self.state == "failed":
            self.stop_rotation()
            return

        self.rotate_for_scan_matching()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = DDSMAutoLocalizer()
    try:
        rclpy.spin(node)
    finally:
        node.stop_rotation()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
