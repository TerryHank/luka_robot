#!/usr/bin/env python3
"""Normalize elevator backends behind a stable ROS 2 topic interface."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, replace

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile
from std_msgs.msg import Bool, String


@dataclass(frozen=True)
class ElevatorStatus:
    available: bool = False
    door: str = "unknown"
    floor_id: str = ""
    car_present: bool = False
    motion: str = "unknown"
    backend: str = "manual"
    updated_at: float = 0.0


def status_json(status: ElevatorStatus) -> str:
    return json.dumps(asdict(status), ensure_ascii=False, sort_keys=True)


def parse_manual_status(payload: str, previous: ElevatorStatus) -> ElevatorStatus:
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise ValueError("manual elevator status must be a JSON object")
    door = str(data.get("door", previous.door)).strip().lower()
    motion = str(data.get("motion", previous.motion)).strip().lower()
    if door not in {"open", "closed", "opening", "closing", "unknown"}:
        raise ValueError(f"invalid elevator door state: {door}")
    if motion not in {"stopped", "moving", "unknown"}:
        raise ValueError(f"invalid elevator motion state: {motion}")
    return ElevatorStatus(
        available=bool(data.get("available", previous.available)),
        door=door,
        floor_id=str(data.get("floor_id", previous.floor_id)).strip(),
        car_present=bool(data.get("car_present", previous.car_present)),
        motion=motion,
        backend=previous.backend,
        updated_at=time.time(),
    )


class DDSMElevatorAdapter(Node):
    def __init__(self) -> None:
        super().__init__("ddsm_elevator_adapter")
        self.declare_parameter("backend", "manual")
        self.declare_parameter("command_topic", "/hotel/elevator/command")
        self.declare_parameter("status_topic", "/hotel/elevator/status")
        self.declare_parameter("manual_status_topic", "/hotel/elevator/manual/status")
        self.declare_parameter(
            "manual_pending_command_topic", "/hotel/elevator/manual/pending_command"
        )
        self.declare_parameter("initial_floor_id", "")

        backend = str(self.get_parameter("backend").value).strip().lower()
        if backend != "manual":
            raise ValueError(
                f"unsupported elevator backend {backend!r}; vendor protocol adapter is not installed"
            )
        self.status = ElevatorStatus(
            backend=backend,
            floor_id=str(self.get_parameter("initial_floor_id").value).strip(),
            updated_at=time.time(),
        )
        qos = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.status_pub = self.create_publisher(
            String, str(self.get_parameter("status_topic").value), qos
        )
        self.pending_command_pub = self.create_publisher(
            String,
            str(self.get_parameter("manual_pending_command_topic").value),
            qos,
        )
        self.create_subscription(
            String,
            str(self.get_parameter("manual_status_topic").value),
            self.on_manual_status,
            10,
        )
        self.create_subscription(
            String,
            str(self.get_parameter("command_topic").value),
            self.on_command,
            10,
        )
        self.publish_status()
        self.get_logger().info(
            "elevator adapter ready | backend=manual; waiting for manual status"
        )

    def publish_status(self) -> None:
        msg = String()
        msg.data = status_json(self.status)
        self.status_pub.publish(msg)

    def on_manual_status(self, msg: String) -> None:
        try:
            self.status = parse_manual_status(msg.data, self.status)
        except (json.JSONDecodeError, ValueError) as exc:
            self.get_logger().error(f"invalid manual elevator status: {exc}")
            return
        self.publish_status()

    def on_command(self, msg: String) -> None:
        try:
            command = json.loads(msg.data)
            if not isinstance(command, dict) or not str(command.get("command", "")):
                raise ValueError("command must be a JSON object with a command field")
        except (json.JSONDecodeError, ValueError) as exc:
            self.get_logger().error(f"invalid elevator command: {exc}")
            return
        pending = String()
        pending.data = msg.data
        self.pending_command_pub.publish(pending)
        self.status = replace(self.status, available=True, updated_at=time.time())
        self.publish_status()
        self.get_logger().info(f"manual elevator action required: {msg.data}")


def main(args=None) -> None:
    rclpy.init(args=args)
    node = DDSMElevatorAdapter()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        node.get_logger().info("elevator adapter stopped")
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
