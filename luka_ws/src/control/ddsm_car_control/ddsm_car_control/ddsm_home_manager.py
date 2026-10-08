#!/usr/bin/env python3
import hashlib
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

import rclpy
import yaml
from geometry_msgs.msg import PoseStamped, Quaternion
from nav2_msgs.action import NavigateToPose
from rclpy.action import ActionClient
from rclpy.duration import Duration
from rclpy.node import Node
from rclpy.time import Time
from std_msgs.msg import Empty, String
from tf2_ros import Buffer, TransformException, TransformListener


PathLike = Union[str, Path]


@dataclass
class HomePose:
    configured: bool
    frame_id: str
    x: float
    y: float
    yaw: float
    map_file: str = ""
    map_sha256: str = ""


def normalize_angle(angle: float) -> float:
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


def _read_yaml(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} does not contain a YAML mapping")
    return data


def _map_image_path(map_file: Path) -> Optional[Path]:
    data = _read_yaml(map_file)
    image = data.get("image")
    if not image:
        return None
    image_path = Path(str(image))
    if not image_path.is_absolute():
        image_path = map_file.parent / image_path
    return image_path


def compute_map_identity(map_file: PathLike) -> str:
    path = Path(map_file).expanduser()
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    image_path = _map_image_path(path)
    if image_path is not None and image_path.exists():
        digest.update(b"\n--map-image--\n")
        digest.update(image_path.read_bytes())
    return digest.hexdigest()


def load_home_pose(path: PathLike) -> HomePose:
    data = _read_yaml(Path(path).expanduser())
    return HomePose(
        configured=bool(data.get("configured", True)),
        frame_id=str(data.get("frame_id", "map")),
        x=float(data.get("x", 0.0)),
        y=float(data.get("y", 0.0)),
        yaw=normalize_angle(float(data.get("yaw", 0.0))),
        map_file=str(data.get("map_file", "")),
        map_sha256=str(data.get("map_sha256", "")),
    )


def dump_home_pose(path: PathLike, pose: HomePose) -> None:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "configured": bool(pose.configured),
        "frame_id": pose.frame_id,
        "x": float(pose.x),
        "y": float(pose.y),
        "yaw": float(normalize_angle(pose.yaw)),
        "map_file": pose.map_file,
        "map_sha256": pose.map_sha256,
    }
    target.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def map_identity_matches(pose: HomePose, current_map_file: PathLike) -> bool:
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


def make_pose_stamped(pose: HomePose) -> PoseStamped:
    msg = PoseStamped()
    msg.header.frame_id = pose.frame_id
    msg.pose.position.x = pose.x
    msg.pose.position.y = pose.y
    msg.pose.position.z = 0.0
    msg.pose.orientation = yaw_to_quaternion(pose.yaw)
    return msg


def make_navigate_goal(pose: HomePose) -> NavigateToPose.Goal:
    goal = NavigateToPose.Goal()
    goal.pose = make_pose_stamped(pose)
    return goal


class DDSMHomeManager(Node):
    def __init__(self) -> None:
        super().__init__("ddsm_home_manager")

        self.declare_parameter("home_pose_file", "/home/sunrise/luka_ws/common/config/home_pose.yaml")
        self.declare_parameter("map_file", "/home/sunrise/luka_ws/map/maps/ddsm_map.yaml")
        self.declare_parameter("map_frame", "map")
        self.declare_parameter("base_frame", "base_link")
        self.declare_parameter("navigate_action", "navigate_to_pose")
        self.declare_parameter("tf_timeout", 1.0)

        self.home_pose_file = Path(
            str(self.get_parameter("home_pose_file").value)
        ).expanduser()
        self.map_file = Path(str(self.get_parameter("map_file").value)).expanduser()
        self.map_frame = str(self.get_parameter("map_frame").value)
        self.base_frame = str(self.get_parameter("base_frame").value)
        self.tf_timeout_s = float(self.get_parameter("tf_timeout").value)

        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        self.action_client = ActionClient(
            self,
            NavigateToPose,
            str(self.get_parameter("navigate_action").value),
        )
        self.current_goal_handle = None

        self.status_pub = self.create_publisher(String, "/home/status", 10)
        self.pose_pub = self.create_publisher(PoseStamped, "/home/pose", 10)
        self.create_subscription(Empty, "/home/set_current", self.on_set_current, 10)
        self.create_subscription(Empty, "/home/go", self.on_go_home, 10)
        self.create_subscription(Empty, "/home/cancel", self.on_cancel, 10)

        self.publish_status("idle")
        self.publish_home_pose_if_available()
        self.get_logger().info(
            "DDSM home manager ready | "
            f"home_pose_file={self.home_pose_file} map_file={self.map_file}"
        )

    def publish_status(self, status: str) -> None:
        msg = String()
        msg.data = status
        self.status_pub.publish(msg)
        self.get_logger().info(f"home status: {status}")

    def publish_home_pose_if_available(self) -> None:
        try:
            pose = load_home_pose(self.home_pose_file)
        except (OSError, ValueError):
            return
        if pose.configured:
            self.pose_pub.publish(make_pose_stamped(pose))

    def current_pose_from_tf(self) -> HomePose:
        transform = self.tf_buffer.lookup_transform(
            self.map_frame,
            self.base_frame,
            Time(),
            timeout=Duration(seconds=self.tf_timeout_s),
        )
        translation = transform.transform.translation
        rotation = transform.transform.rotation
        map_sha256 = ""
        try:
            map_sha256 = compute_map_identity(self.map_file)
        except OSError as exc:
            self.get_logger().warn(f"unable to hash current map {self.map_file}: {exc}")

        return HomePose(
            configured=True,
            frame_id=self.map_frame,
            x=float(translation.x),
            y=float(translation.y),
            yaw=yaw_from_quaternion(rotation),
            map_file=str(self.map_file),
            map_sha256=map_sha256,
        )

    def on_set_current(self, _msg: Empty) -> None:
        try:
            pose = self.current_pose_from_tf()
        except TransformException as exc:
            self.publish_status("no_map_to_base_link")
            self.get_logger().warn(f"cannot set home without TF: {exc}")
            return
        dump_home_pose(self.home_pose_file, pose)
        self.pose_pub.publish(make_pose_stamped(pose))
        self.publish_status("home_saved")

    def on_go_home(self, _msg: Empty) -> None:
        try:
            pose = load_home_pose(self.home_pose_file)
        except OSError:
            self.publish_status("no_home_pose")
            return
        except ValueError as exc:
            self.publish_status("bad_home_pose")
            self.get_logger().warn(str(exc))
            return

        if not pose.configured:
            self.publish_status("home_not_configured")
            return
        if pose.frame_id != self.map_frame:
            self.publish_status("home_frame_mismatch")
            return
        if not map_identity_matches(pose, self.map_file):
            self.publish_status("map_mismatch")
            return
        if not self.action_client.wait_for_server(timeout_sec=2.0):
            self.publish_status("nav2_unavailable")
            return

        goal = make_navigate_goal(pose)
        goal.pose.header.stamp = self.get_clock().now().to_msg()
        self.pose_pub.publish(goal.pose)
        self.publish_status("going_home")
        send_future = self.action_client.send_goal_async(goal)
        send_future.add_done_callback(self.on_goal_response)

    def on_goal_response(self, future) -> None:
        goal_handle = future.result()
        if not goal_handle.accepted:
            self.publish_status("rejected")
            return
        self.current_goal_handle = goal_handle
        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(self.on_goal_result)

    def on_goal_result(self, future) -> None:
        result = future.result()
        self.current_goal_handle = None
        if result.status == 4:
            self.publish_status("arrived")
        else:
            self.publish_status(f"failed:{result.status}")

    def on_cancel(self, _msg: Empty) -> None:
        if self.current_goal_handle is None:
            self.publish_status("idle")
            return
        cancel_future = self.current_goal_handle.cancel_goal_async()
        cancel_future.add_done_callback(lambda _future: self.publish_status("cancelled"))


def main(args=None) -> None:
    rclpy.init(args=args)
    node = DDSMHomeManager()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
