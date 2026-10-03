#!/usr/bin/env python3
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Union

import rclpy
import yaml
from action_msgs.msg import GoalStatus
from geometry_msgs.msg import PoseStamped, Quaternion
from nav2_msgs.action import NavigateToPose
from nav_msgs.msg import Path as NavPath
from rclpy.action import ActionClient
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from std_msgs.msg import Bool, Empty as EmptyMsg, String
from std_srvs.srv import Empty as EmptySrv
from visualization_msgs.msg import Marker, MarkerArray


PathLike = Union[str, Path]


@dataclass
class Waypoint:
    id: str
    name: str
    x: float
    y: float
    yaw: float
    waypoint_type: str = "stop"
    dwell_sec: float = 0.0
    final_approach: bool = False


@dataclass
class PatrolRoute:
    route_id: str
    loop: bool
    waypoints: List[Waypoint] = field(default_factory=list)


@dataclass
class PatrolCursor:
    route_len: int
    loop: bool
    current_index: int = 0

    def advance(self) -> Optional[int]:
        if self.route_len <= 0:
            return None
        next_index = self.current_index + 1
        if next_index >= self.route_len:
            if not self.loop:
                return None
            next_index = 0
        self.current_index = next_index
        return self.current_index


def normalize_angle(angle: float) -> float:
    if -math.pi < angle <= math.pi:
        return angle
    wrapped = (angle + math.pi) % (2.0 * math.pi) - math.pi
    if wrapped == -math.pi:
        return math.pi
    return wrapped


def yaw_to_quaternion(yaw: float) -> Quaternion:
    quat = Quaternion()
    half = yaw * 0.5
    quat.x = 0.0
    quat.y = 0.0
    quat.z = math.sin(half)
    quat.w = math.cos(half)
    return quat


def yaw_from_quaternion(quat: Quaternion) -> float:
    return math.atan2(
        2.0 * (quat.w * quat.z + quat.x * quat.y),
        1.0 - 2.0 * (quat.y * quat.y + quat.z * quat.z),
    )


def waypoint_requires_final_approach(waypoint: Waypoint) -> bool:
    return waypoint.final_approach or waypoint.waypoint_type in {
        "delivery",
        "delivery_stop",
        "dock",
        "final",
        "final_approach",
    }


def _waypoint_from_dict(data: dict, index: int) -> Waypoint:
    waypoint_type = str(data.get("type", data.get("waypoint_type", "stop")))
    final_approach = bool(
        data.get(
            "final_approach",
            waypoint_type in {"delivery", "delivery_stop", "dock", "final", "final_approach"},
        )
    )
    waypoint_id = str(data.get("id", f"wp_{index + 1:03d}"))
    return Waypoint(
        id=waypoint_id,
        name=str(data.get("name", waypoint_id)),
        x=float(data.get("x", 0.0)),
        y=float(data.get("y", 0.0)),
        yaw=normalize_angle(float(data.get("yaw", 0.0))),
        waypoint_type=waypoint_type,
        dwell_sec=float(data.get("dwell_sec", 0.0)),
        final_approach=final_approach,
    )


def _waypoint_to_dict(waypoint: Waypoint) -> dict:
    return {
        "id": waypoint.id,
        "name": waypoint.name,
        "x": float(waypoint.x),
        "y": float(waypoint.y),
        "yaw": float(normalize_angle(waypoint.yaw)),
        "type": waypoint.waypoint_type,
        "dwell_sec": float(waypoint.dwell_sec),
        "final_approach": bool(waypoint.final_approach),
    }


def load_route(path: PathLike) -> PatrolRoute:
    route_path = Path(path).expanduser()
    data = yaml.safe_load(route_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{route_path} does not contain a YAML mapping")
    waypoints = data.get("waypoints", [])
    if not isinstance(waypoints, list):
        raise ValueError("route waypoints must be a list")
    return PatrolRoute(
        route_id=str(data.get("route_id", route_path.stem)),
        loop=bool(data.get("loop", False)),
        waypoints=[
            _waypoint_from_dict(waypoint, index)
            for index, waypoint in enumerate(waypoints)
            if isinstance(waypoint, dict)
        ],
    )


def dump_route(path: PathLike, route: PatrolRoute) -> None:
    route_path = Path(path).expanduser()
    route_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "route_id": route.route_id,
        "loop": bool(route.loop),
        "waypoints": [_waypoint_to_dict(waypoint) for waypoint in route.waypoints],
    }
    route_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def make_pose_stamped(waypoint: Waypoint, frame_id: str) -> PoseStamped:
    pose = PoseStamped()
    pose.header.frame_id = frame_id
    pose.pose.position.x = float(waypoint.x)
    pose.pose.position.y = float(waypoint.y)
    pose.pose.position.z = 0.0
    pose.pose.orientation = yaw_to_quaternion(waypoint.yaw)
    return pose


def append_pose_waypoint(
    route: PatrolRoute,
    pose: PoseStamped,
    *,
    default_dwell_sec: float,
) -> Waypoint:
    index = len(route.waypoints) + 1
    waypoint_id = f"wp_{index:03d}"
    waypoint = Waypoint(
        id=waypoint_id,
        name=waypoint_id,
        x=float(pose.pose.position.x),
        y=float(pose.pose.position.y),
        yaw=normalize_angle(yaw_from_quaternion(pose.pose.orientation)),
        waypoint_type="stop",
        dwell_sec=float(default_dwell_sec),
        final_approach=False,
    )
    route.waypoints.append(waypoint)
    return waypoint


def make_route_path(route: PatrolRoute, frame_id: str) -> NavPath:
    path = NavPath()
    path.header.frame_id = frame_id
    path.poses = [make_pose_stamped(waypoint, frame_id) for waypoint in route.waypoints]
    return path


def _set_marker_color(marker: Marker, *, current: bool, text: bool) -> None:
    marker.color.a = 1.0
    if current:
        marker.color.r = 1.0
        marker.color.g = 0.18 if text else 0.25
        marker.color.b = 0.12 if text else 0.2
    else:
        marker.color.r = 0.1
        marker.color.g = 0.85 if text else 0.55
        marker.color.b = 0.9 if text else 0.35


def make_route_markers(
    route: PatrolRoute,
    frame_id: str,
    current_index: Optional[int] = None,
) -> MarkerArray:
    markers = MarkerArray()
    for index, waypoint in enumerate(route.waypoints):
        marker = Marker()
        marker.header.frame_id = frame_id
        marker.ns = "patrol_waypoints"
        marker.id = index
        marker.type = Marker.SPHERE
        marker.action = Marker.ADD
        marker.pose.position.x = float(waypoint.x)
        marker.pose.position.y = float(waypoint.y)
        marker.pose.position.z = 0.08
        marker.pose.orientation.w = 1.0
        marker.scale.x = 0.22 if index == current_index else 0.16
        marker.scale.y = marker.scale.x
        marker.scale.z = 0.10
        _set_marker_color(marker, current=index == current_index, text=False)
        markers.markers.append(marker)

    text_offset = len(route.waypoints)
    for index, waypoint in enumerate(route.waypoints):
        marker = Marker()
        marker.header.frame_id = frame_id
        marker.ns = "patrol_waypoint_labels"
        marker.id = text_offset + index
        marker.type = Marker.TEXT_VIEW_FACING
        marker.action = Marker.ADD
        marker.pose.position.x = float(waypoint.x)
        marker.pose.position.y = float(waypoint.y)
        marker.pose.position.z = 0.35
        marker.pose.orientation.w = 1.0
        marker.scale.z = 0.18 if index == current_index else 0.14
        marker.text = waypoint.name or waypoint.id
        _set_marker_color(marker, current=index == current_index, text=True)
        markers.markers.append(marker)

    return markers


def classify_final_approach_status(status: str) -> str:
    status = str(status)
    if status == "final_reached":
        return "success"
    failure_tokens = [
        "blocked_front",
        "failed",
        "goal_rejected",
        "missing_final_goal",
        "nav_server_unavailable",
        "rejected_goal_frame",
        "timeout",
    ]
    if status == "cancelled" or any(token in status for token in failure_tokens):
        return "failure"
    return "pending"


def safe_service_is_ready(client, *, context_ok: bool) -> bool:
    if not context_ok:
        return False
    try:
        return bool(client.service_is_ready())
    except Exception:
        return False


class DDSMPatrolManager(Node):
    def __init__(self) -> None:
        super().__init__("ddsm_patrol_manager")

        self.declare_parameter("route_file", "/home/sunrise/luka_ws/common/config/patrol_route.yaml")
        self.declare_parameter("map_frame", "map")
        self.declare_parameter("navigate_action", "navigate_to_pose")
        self.declare_parameter("final_goal_topic", "/goal_pose")
        self.declare_parameter("final_status_topic", "/final_approach/status")
        self.declare_parameter("localization_ready_topic", "/localization/ready")
        self.declare_parameter("require_localization_ready", True)
        self.declare_parameter("default_dwell_sec", 0.0)
        self.declare_parameter("retry_count", 1)
        self.declare_parameter("stop_on_failure", True)
        self.declare_parameter("final_approach_timeout", 90.0)
        self.declare_parameter("nav_goal_timeout", 180.0)
        self.declare_parameter("publish_period", 0.5)

        self.route_file = Path(str(self.get_parameter("route_file").value)).expanduser()
        self.map_frame = str(self.get_parameter("map_frame").value)
        self.default_dwell_sec = float(self.get_parameter("default_dwell_sec").value)
        self.retry_count = int(self.get_parameter("retry_count").value)
        self.stop_on_failure = bool(self.get_parameter("stop_on_failure").value)
        self.require_localization_ready = bool(
            self.get_parameter("require_localization_ready").value
        )
        self.final_approach_timeout = float(
            self.get_parameter("final_approach_timeout").value
        )
        self.nav_goal_timeout = float(self.get_parameter("nav_goal_timeout").value)

        self.route = PatrolRoute(route_id="manual", loop=False, waypoints=[])
        self.cursor: Optional[PatrolCursor] = None
        self.state = "idle"
        self.localization_ready = not self.require_localization_ready
        self.current_goal_handle = None
        self.current_waypoint: Optional[Waypoint] = None
        self.active_goal_token = 0
        self.nav_started_at: Optional[float] = None
        self.retry_attempt = 0
        self.dwell_until: Optional[float] = None
        self.final_started_at: Optional[float] = None
        self.requested_loop = False

        self.nav_client = ActionClient(
            self,
            NavigateToPose,
            str(self.get_parameter("navigate_action").value),
        )
        self.final_cancel_client = self.create_client(EmptySrv, "/final_approach/cancel")

        self.final_goal_pub = self.create_publisher(
            PoseStamped,
            str(self.get_parameter("final_goal_topic").value),
            10,
        )
        self.home_go_pub = self.create_publisher(EmptyMsg, "/home/go", 10)
        self.status_pub = self.create_publisher(String, "/patrol/status", 10)
        self.current_waypoint_pub = self.create_publisher(
            String,
            "/patrol/current_waypoint",
            10,
        )
        self.path_pub = self.create_publisher(NavPath, "/patrol/route_path", 1)
        self.markers_pub = self.create_publisher(MarkerArray, "/patrol/markers", 1)

        self.create_subscription(PoseStamped, "/patrol/add_pose", self.on_add_pose, 10)
        self.create_subscription(EmptyMsg, "/patrol/clear", self.on_clear, 10)
        self.create_subscription(EmptyMsg, "/patrol/start_once", self.on_start_once, 10)
        self.create_subscription(EmptyMsg, "/patrol/start_loop", self.on_start_loop, 10)
        self.create_subscription(EmptyMsg, "/patrol/pause", self.on_pause, 10)
        self.create_subscription(EmptyMsg, "/patrol/resume", self.on_resume, 10)
        self.create_subscription(EmptyMsg, "/patrol/stop", self.on_stop, 10)
        self.create_subscription(EmptyMsg, "/patrol/go_home", self.on_go_home, 10)
        self.create_subscription(String, "/patrol/load_route", self.on_load_route, 10)
        self.create_subscription(String, "/patrol/save_route", self.on_save_route, 10)
        self.create_subscription(
            Bool,
            str(self.get_parameter("localization_ready_topic").value),
            self.on_localization_ready,
            10,
        )
        self.create_subscription(
            String,
            str(self.get_parameter("final_status_topic").value),
            self.on_final_status,
            10,
        )

        period = float(self.get_parameter("publish_period").value)
        self.create_timer(period, self.on_timer)

        self.try_load_default_route()
        self.publish_status("idle")
        self.get_logger().info(
            "DDSM patrol manager ready | "
            f"route_file={self.route_file} require_localization_ready={self.require_localization_ready}"
        )

    def now_seconds(self) -> float:
        return self.get_clock().now().nanoseconds / 1e9

    def publish_status(self, status: str) -> None:
        self.state = status
        msg = String()
        msg.data = status
        self.status_pub.publish(msg)
        self.get_logger().info(f"patrol status: {status}")

    def publish_current_waypoint(self) -> None:
        msg = String()
        if self.current_waypoint is None or self.cursor is None:
            msg.data = ""
        else:
            msg.data = (
                f"{self.cursor.current_index + 1}/{len(self.route.waypoints)} "
                f"{self.current_waypoint.id} {self.current_waypoint.name} state={self.state}"
            )
        self.current_waypoint_pub.publish(msg)

    def publish_route_visuals(self) -> None:
        current_index = self.cursor.current_index if self.cursor is not None else None
        path = make_route_path(self.route, self.map_frame)
        path.header.stamp = self.get_clock().now().to_msg()
        for pose in path.poses:
            pose.header.stamp = path.header.stamp
        self.path_pub.publish(path)

        markers = make_route_markers(self.route, self.map_frame, current_index)
        stamp = self.get_clock().now().to_msg()
        for marker in markers.markers:
            marker.header.stamp = stamp
        self.markers_pub.publish(markers)

    def try_load_default_route(self) -> None:
        if not self.route_file.exists():
            return
        try:
            self.route = load_route(self.route_file)
        except (OSError, ValueError) as exc:
            self.get_logger().warn(f"cannot load patrol route {self.route_file}: {exc}")

    def patrol_is_active(self) -> bool:
        return (
            self.state.startswith("navigating:")
            or self.state.startswith("final_approach:")
            or self.state.startswith("dwell:")
            or self.state.startswith("retry:")
            or self.state == "waiting_localization"
        )

    def start(self, *, loop: bool) -> None:
        if self.patrol_is_active():
            self.publish_status(f"already_running:{self.current_waypoint.id if self.current_waypoint else 'unknown'}")
            return
        if not self.route.waypoints and self.route_file.exists():
            self.try_load_default_route()
        if not self.route.waypoints:
            self.publish_status("route_empty")
            return
        self.requested_loop = loop
        self.route.loop = loop
        self.cursor = PatrolCursor(route_len=len(self.route.waypoints), loop=loop)
        self.retry_attempt = 0
        if self.require_localization_ready and not self.localization_ready:
            self.publish_status("waiting_localization")
            return
        self.begin_current_waypoint()

    def begin_current_waypoint(self) -> None:
        if self.cursor is None:
            self.publish_status("idle")
            return
        if not self.route.waypoints:
            self.publish_status("route_empty")
            return
        self.current_waypoint = self.route.waypoints[self.cursor.current_index]
        self.publish_current_waypoint()
        if waypoint_requires_final_approach(self.current_waypoint):
            self.send_final_approach_goal(self.current_waypoint)
        else:
            self.send_nav_goal(self.current_waypoint)

    def send_nav_goal(self, waypoint: Waypoint) -> None:
        if not self.nav_client.wait_for_server(timeout_sec=2.0):
            self.handle_waypoint_failure("nav_server_unavailable")
            return
        pose = make_pose_stamped(waypoint, self.map_frame)
        pose.header.stamp = self.get_clock().now().to_msg()
        goal = NavigateToPose.Goal()
        goal.pose = pose
        self.active_goal_token += 1
        goal_token = self.active_goal_token
        self.nav_started_at = self.now_seconds()
        self.publish_status(f"navigating:{waypoint.id}")
        future = self.nav_client.send_goal_async(goal)
        future.add_done_callback(lambda done, token=goal_token: self.on_nav_goal_response(done, token))

    def on_nav_goal_response(self, future, goal_token: int) -> None:
        if goal_token != self.active_goal_token:
            return
        if self.current_waypoint is None or not self.state.startswith("navigating:"):
            return
        try:
            goal_handle = future.result()
        except Exception as exc:
            self.handle_waypoint_failure(f"nav_goal_error:{exc}")
            return
        if not goal_handle.accepted:
            self.handle_waypoint_failure("nav_goal_rejected")
            return
        self.current_goal_handle = goal_handle
        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(lambda done, token=goal_token: self.on_nav_result(done, token))

    def on_nav_result(self, future, goal_token: int) -> None:
        if goal_token != self.active_goal_token:
            return
        self.current_goal_handle = None
        self.nav_started_at = None
        if self.current_waypoint is None or not self.state.startswith("navigating:"):
            return
        try:
            result = future.result()
        except Exception as exc:
            self.handle_waypoint_failure(f"nav_result_error:{exc}")
            return
        if result.status != GoalStatus.STATUS_SUCCEEDED:
            self.handle_waypoint_failure(f"nav_failed:{result.status}")
            return
        self.handle_waypoint_success()

    def send_final_approach_goal(self, waypoint: Waypoint) -> None:
        pose = make_pose_stamped(waypoint, self.map_frame)
        pose.header.stamp = self.get_clock().now().to_msg()
        self.final_started_at = self.now_seconds()
        self.publish_status(f"final_approach:{waypoint.id}")
        self.final_goal_pub.publish(pose)

    def on_final_status(self, msg: String) -> None:
        if self.current_waypoint is None or not self.state.startswith("final_approach:"):
            return
        classification = classify_final_approach_status(msg.data)
        if classification == "success":
            self.final_started_at = None
            self.handle_waypoint_success()
        elif classification == "failure":
            self.final_started_at = None
            self.handle_waypoint_failure(f"final_approach:{msg.data}")

    def handle_waypoint_success(self) -> None:
        self.retry_attempt = 0
        dwell = self.current_waypoint.dwell_sec if self.current_waypoint is not None else 0.0
        if dwell > 0.0:
            self.dwell_until = self.now_seconds() + dwell
            self.publish_status(f"dwell:{self.current_waypoint.id}")
            return
        self.advance_or_complete()

    def handle_waypoint_failure(self, reason: str) -> None:
        if self.current_waypoint is None:
            self.publish_status(f"failed:{reason}")
            return
        if self.retry_attempt < self.retry_count:
            self.retry_attempt += 1
            self.publish_status(f"retry:{self.current_waypoint.id}:{reason}")
            self.begin_current_waypoint()
            return
        self.current_goal_handle = None
        self.nav_started_at = None
        self.publish_status(f"failed:{self.current_waypoint.id}:{reason}")
        if not self.stop_on_failure:
            self.retry_attempt = 0
            self.advance_or_complete()

    def advance_or_complete(self) -> None:
        if self.cursor is None:
            self.publish_status("idle")
            return
        self.nav_started_at = None
        next_index = self.cursor.advance()
        if next_index is None:
            self.current_waypoint = None
            self.publish_status("completed")
            return
        self.begin_current_waypoint()

    def cancel_active_motion(self) -> None:
        self.active_goal_token += 1
        self.nav_started_at = None
        if self.current_goal_handle is not None:
            self.current_goal_handle.cancel_goal_async()
            self.current_goal_handle = None
        if safe_service_is_ready(self.final_cancel_client, context_ok=rclpy.ok()):
            self.final_cancel_client.call_async(EmptySrv.Request())

    def on_add_pose(self, pose: PoseStamped) -> None:
        if pose.header.frame_id and pose.header.frame_id != self.map_frame:
            self.publish_status(f"add_pose_frame_mismatch:{pose.header.frame_id}")
            return
        waypoint = append_pose_waypoint(
            self.route,
            pose,
            default_dwell_sec=self.default_dwell_sec,
        )
        self.publish_status(f"added:{waypoint.id}")
        self.publish_route_visuals()

    def on_clear(self, _msg: EmptyMsg) -> None:
        self.cancel_active_motion()
        self.route.waypoints.clear()
        self.cursor = None
        self.current_waypoint = None
        self.publish_status("cleared")
        self.publish_route_visuals()

    def on_start_once(self, _msg: EmptyMsg) -> None:
        self.start(loop=False)

    def on_start_loop(self, _msg: EmptyMsg) -> None:
        self.start(loop=True)

    def on_pause(self, _msg: EmptyMsg) -> None:
        self.cancel_active_motion()
        self.publish_status("paused")

    def on_resume(self, _msg: EmptyMsg) -> None:
        if self.cursor is None:
            self.publish_status("idle")
            return
        if self.require_localization_ready and not self.localization_ready:
            self.publish_status("waiting_localization")
            return
        self.begin_current_waypoint()

    def on_stop(self, _msg: EmptyMsg) -> None:
        self.cancel_active_motion()
        self.cursor = None
        self.current_waypoint = None
        self.retry_attempt = 0
        self.dwell_until = None
        self.nav_started_at = None
        self.final_started_at = None
        self.publish_status("stopped")

    def on_go_home(self, _msg: EmptyMsg) -> None:
        self.cancel_active_motion()
        self.cursor = None
        self.current_waypoint = None
        self.home_go_pub.publish(EmptyMsg())
        self.publish_status("going_home")

    def on_load_route(self, msg: String) -> None:
        route_path = Path(msg.data.strip()).expanduser() if msg.data.strip() else self.route_file
        try:
            self.route = load_route(route_path)
        except (OSError, ValueError) as exc:
            self.publish_status("load_failed")
            self.get_logger().warn(f"cannot load route {route_path}: {exc}")
            return
        self.route_file = route_path
        self.cursor = None
        self.current_waypoint = None
        self.publish_status(f"loaded:{self.route.route_id}")
        self.publish_route_visuals()

    def on_save_route(self, msg: String) -> None:
        route_path = Path(msg.data.strip()).expanduser() if msg.data.strip() else self.route_file
        try:
            dump_route(route_path, self.route)
        except OSError as exc:
            self.publish_status("save_failed")
            self.get_logger().warn(f"cannot save route {route_path}: {exc}")
            return
        self.route_file = route_path
        self.publish_status(f"saved:{route_path}")

    def on_localization_ready(self, msg: Bool) -> None:
        self.localization_ready = bool(msg.data)
        if self.state == "waiting_localization" and self.localization_ready:
            self.begin_current_waypoint()

    def on_timer(self) -> None:
        self.publish_current_waypoint()
        self.publish_route_visuals()
        if self.state.startswith("navigating:") and self.nav_started_at is not None:
            if self.now_seconds() - self.nav_started_at >= self.nav_goal_timeout:
                self.cancel_active_motion()
                self.handle_waypoint_failure("nav_goal_timeout")
                return
        if self.state.startswith("dwell:") and self.dwell_until is not None:
            if self.now_seconds() >= self.dwell_until:
                self.dwell_until = None
                self.advance_or_complete()
        if self.state.startswith("final_approach:") and self.final_started_at is not None:
            if self.now_seconds() - self.final_started_at >= self.final_approach_timeout:
                self.final_started_at = None
                self.handle_waypoint_failure("final_approach_timeout")


def main(args=None) -> None:
    rclpy.init(args=args)
    node = DDSMPatrolManager()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        if rclpy.ok():
            node.cancel_active_motion()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
