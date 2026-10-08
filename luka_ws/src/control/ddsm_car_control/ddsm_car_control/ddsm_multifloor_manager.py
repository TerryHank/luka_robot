#!/usr/bin/env python3
"""Semi-automatic multi-floor mission manager for hotel navigation."""

from __future__ import annotations

import json
import math
import os
import subprocess
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Dict, Optional, Union

import yaml

import rclpy
from geometry_msgs.msg import PoseWithCovarianceStamped
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile
from std_msgs.msg import Empty, String
from std_srvs.srv import Empty as EmptySrv

PathLike = Union[str, Path]


@dataclass(frozen=True)
class InitialPose:
    x: float
    y: float
    yaw: float


@dataclass(frozen=True)
class ElevatorPose:
    entry_destination_id: str
    exit_initial_pose: InitialPose


@dataclass(frozen=True)
class FloorConfig:
    floor_id: str
    map: str
    semantic_map: str
    elevator_poses: Dict[str, ElevatorPose]


@dataclass(frozen=True)
class DestinationConfig:
    floor_id: str
    destination_id: str
    display_name: str = ""


@dataclass(frozen=True)
class BuildingConfig:
    building_id: str
    current_floor_id: str
    default_elevator_id: str
    floors: Dict[str, FloorConfig]
    destinations: Dict[str, DestinationConfig]


@dataclass(frozen=True)
class FloorMissionPlan:
    requested_destination_id: str
    current_floor_id: str
    target_floor_id: str
    final_destination_id: str
    elevator_id: str
    elevator_entry_destination_id: str
    target_map: str
    target_exit_initial_pose: InitialPose
    is_cross_floor: bool


@dataclass(frozen=True)
class FloorMissionState:
    state: str = "idle"
    requested_destination_id: str = ""
    current_floor_id: str = ""
    target_floor_id: str = ""
    elevator_id: str = ""
    elevator_entry_destination_id: str = ""
    final_destination_id: str = ""
    target_map: str = ""
    instruction: str = ""
    error: str = ""
    updated_at: float = 0.0


@dataclass(frozen=True)
class ElevatorStatus:
    available: bool = False
    door: str = "unknown"
    floor_id: str = ""
    car_present: bool = False
    motion: str = "unknown"


def parse_elevator_status(payload: str) -> ElevatorStatus:
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise ValueError("elevator status must be a JSON object")
    return ElevatorStatus(
        available=bool(data.get("available", False)),
        door=str(data.get("door", "unknown")).strip().lower(),
        floor_id=str(data.get("floor_id", "")).strip(),
        car_present=bool(data.get("car_present", False)),
        motion=str(data.get("motion", "unknown")).strip().lower(),
    )


def make_elevator_command(
    command: str, elevator_id: str, floor_id: str
) -> str:
    return json.dumps(
        {
            "command": str(command),
            "elevator_id": str(elevator_id),
            "floor_id": str(floor_id),
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _as_mapping(value, name: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a mapping")
    return value


def load_building_config(path: PathLike) -> BuildingConfig:
    source = Path(path).expanduser()
    data = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    data = _as_mapping(data, "building config")

    floors = {}
    for floor_id, floor_data in _as_mapping(data.get("floors", {}), "floors").items():
        floor_data = _as_mapping(floor_data, f"floor {floor_id}")
        elevators = {}
        for elevator_id, elevator_data in _as_mapping(
            floor_data.get("elevator_poses", {}), f"floor {floor_id} elevator_poses"
        ).items():
            elevator_data = _as_mapping(elevator_data, f"elevator {elevator_id}")
            pose = _as_mapping(
                elevator_data.get("exit_initial_pose", {}),
                f"elevator {elevator_id} exit_initial_pose",
            )
            elevators[str(elevator_id)] = ElevatorPose(
                entry_destination_id=str(elevator_data["entry_destination_id"]),
                exit_initial_pose=InitialPose(
                    x=float(pose["x"]),
                    y=float(pose["y"]),
                    yaw=float(pose["yaw"]),
                ),
            )
        floors[str(floor_id)] = FloorConfig(
            floor_id=str(floor_id),
            map=str(floor_data["map"]),
            semantic_map=str(floor_data.get("semantic_map", "")),
            elevator_poses=elevators,
        )

    destinations = {}
    for key, value in _as_mapping(data.get("destinations", {}), "destinations").items():
        value = _as_mapping(value, f"destination {key}")
        destinations[str(key)] = DestinationConfig(
            floor_id=str(value["floor_id"]),
            destination_id=str(value["destination_id"]),
            display_name=str(value.get("display_name", "")),
        )

    return BuildingConfig(
        building_id=str(data["building_id"]),
        current_floor_id=str(data["current_floor_id"]),
        default_elevator_id=str(data["default_elevator_id"]),
        floors=floors,
        destinations=destinations,
    )


def resolve_destination_key(building: BuildingConfig, query: str) -> str:
    text = str(query).strip()
    if text in building.destinations:
        return text
    for key, destination in building.destinations.items():
        if text == destination.destination_id or text == destination.display_name:
            return key
    folded = text.casefold()
    for key, destination in building.destinations.items():
        candidates = (key, destination.destination_id, destination.display_name)
        if any(candidate.casefold() == folded for candidate in candidates if candidate):
            return key
    raise KeyError(f"unknown destination: {query}")


def plan_floor_mission(building: BuildingConfig, destination_query: str) -> FloorMissionPlan:
    destination_key = resolve_destination_key(building, destination_query)
    destination = building.destinations[destination_key]
    elevator_id = building.default_elevator_id
    current_floor = building.floors[building.current_floor_id]
    target_floor = building.floors[destination.floor_id]
    is_cross_floor = building.current_floor_id != destination.floor_id

    current_elevator = current_floor.elevator_poses.get(elevator_id)
    target_elevator = target_floor.elevator_poses.get(elevator_id)
    if is_cross_floor and current_elevator is None:
        raise KeyError(
            f"floor {building.current_floor_id} missing elevator {elevator_id}"
        )
    if target_elevator is None:
        raise KeyError(f"floor {destination.floor_id} missing elevator {elevator_id}")

    return FloorMissionPlan(
        requested_destination_id=destination_key,
        current_floor_id=building.current_floor_id,
        target_floor_id=destination.floor_id,
        final_destination_id=destination.destination_id,
        elevator_id=elevator_id,
        elevator_entry_destination_id=(
            current_elevator.entry_destination_id if current_elevator else ""
        ),
        target_map=target_floor.map,
        target_exit_initial_pose=target_elevator.exit_initial_pose,
        is_cross_floor=is_cross_floor,
    )


def dump_floor_state(path: PathLike, state: FloorMissionState) -> None:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        yaml.safe_dump(
            {
                "state": state.state,
                "requested_destination_id": state.requested_destination_id,
                "current_floor_id": state.current_floor_id,
                "target_floor_id": state.target_floor_id,
                "elevator_id": state.elevator_id,
                "elevator_entry_destination_id": state.elevator_entry_destination_id,
                "final_destination_id": state.final_destination_id,
                "target_map": state.target_map,
                "instruction": state.instruction,
                "error": state.error,
                "updated_at": float(state.updated_at or time.time()),
            },
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )


def load_floor_state(path: PathLike) -> FloorMissionState:
    source = Path(path).expanduser()
    if not source.exists():
        return FloorMissionState()
    data = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return FloorMissionState()
    return FloorMissionState(
        state=str(data.get("state", "idle")),
        requested_destination_id=str(data.get("requested_destination_id", "")),
        current_floor_id=str(data.get("current_floor_id", "")),
        target_floor_id=str(data.get("target_floor_id", "")),
        elevator_id=str(data.get("elevator_id", "")),
        elevator_entry_destination_id=str(data.get("elevator_entry_destination_id", "")),
        final_destination_id=str(data.get("final_destination_id", "")),
        target_map=str(data.get("target_map", "")),
        instruction=str(data.get("instruction", "")),
        error=str(data.get("error", "")),
        updated_at=float(data.get("updated_at", 0.0) or 0.0),
    )


def make_status_json(state: FloorMissionState) -> str:
    return json.dumps(
        {
            "state": state.state,
            "requested_destination_id": state.requested_destination_id,
            "current_floor_id": state.current_floor_id,
            "target_floor_id": state.target_floor_id,
            "elevator_id": state.elevator_id,
            "elevator_entry_destination_id": state.elevator_entry_destination_id,
            "final_destination_id": state.final_destination_id,
            "target_map": state.target_map,
            "instruction": state.instruction,
            "error": state.error,
            "updated_at": state.updated_at,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def make_initialpose_msg(
    pose: InitialPose,
    *,
    frame_id: str = "map",
) -> PoseWithCovarianceStamped:
    msg = PoseWithCovarianceStamped()
    msg.header.frame_id = frame_id
    msg.pose.pose.position.x = float(pose.x)
    msg.pose.pose.position.y = float(pose.y)
    half = float(pose.yaw) * 0.5
    msg.pose.pose.orientation.z = math.sin(half)
    msg.pose.pose.orientation.w = math.cos(half)
    msg.pose.covariance[0] = 0.05 * 0.05
    msg.pose.covariance[7] = 0.05 * 0.05
    msg.pose.covariance[35] = 0.10 * 0.10
    return msg


class DDSMFloorMissionManager(Node):
    def __init__(self) -> None:
        super().__init__("ddsm_multifloor_manager")
        self.declare_parameter(
            "building_config_file",
            "/home/sunrise/luka_ws/common/config/multifloor_building.yaml",
        )
        self.declare_parameter(
            "state_file", "/home/sunrise/luka_ws/common/config/floor_mission_state.yaml"
        )
        self.declare_parameter("goal_topic", "/hotel/floor_goal")
        self.declare_parameter("arrived_topic", "/hotel/floor_transfer/arrived")
        self.declare_parameter("elevator_lobby_ready_topic", "/hotel/elevator/lobby_ready")
        self.declare_parameter("elevator_entered_topic", "/hotel/elevator/entered")
        self.declare_parameter("elevator_exited_topic", "/hotel/elevator/exited")
        self.declare_parameter("elevator_status_topic", "/hotel/elevator/status")
        self.declare_parameter("elevator_command_topic", "/hotel/elevator/command")
        self.declare_parameter("cancel_topic", "/hotel/floor_mission/cancel")
        self.declare_parameter("status_topic", "/hotel/floor_mission/status")
        self.declare_parameter("single_floor_goal_topic", "/hotel/goal_destination")
        self.declare_parameter("mission_cancel_service", "/hotel/mission/cancel_now")
        self.declare_parameter("initial_pose_topic", "/initialpose")
        self.declare_parameter("map_frame", "map")
        self.declare_parameter("restart_script", "/home/sunrise/luka_ws/restart_nav_reset.sh")
        self.declare_parameter("restart_mode", "auto_nav")
        self.declare_parameter("restart_foxglove", "0")
        self.declare_parameter("current_floor_id", "")
        self.declare_parameter("recover_initialpose_count", 5)
        self.declare_parameter("recover_initialpose_period", 0.4)
        self.declare_parameter("recover_delay", 8.0)

        self.building_config_file = Path(
            str(self.get_parameter("building_config_file").value)
        ).expanduser()
        self.state_file = Path(str(self.get_parameter("state_file").value)).expanduser()
        self.restart_script = Path(
            str(self.get_parameter("restart_script").value)
        ).expanduser()
        self.map_frame = str(self.get_parameter("map_frame").value)
        self.recover_initialpose_count = int(
            self.get_parameter("recover_initialpose_count").value
        )
        self.recover_initialpose_period = float(
            self.get_parameter("recover_initialpose_period").value
        )
        self.building = load_building_config(self.building_config_file)
        current_floor_id = str(self.get_parameter("current_floor_id").value).strip()
        if current_floor_id:
            if current_floor_id not in self.building.floors:
                raise ValueError(f"current_floor_id {current_floor_id!r} is not in building floors")
            self.building = replace(self.building, current_floor_id=current_floor_id)

        qos = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.status_pub = self.create_publisher(
            String, str(self.get_parameter("status_topic").value), qos
        )
        self.single_floor_goal_pub = self.create_publisher(
            String, str(self.get_parameter("single_floor_goal_topic").value), 10
        )
        self.initial_pose_pub = self.create_publisher(
            PoseWithCovarianceStamped,
            str(self.get_parameter("initial_pose_topic").value),
            qos,
        )
        self.elevator_command_pub = self.create_publisher(
            String, str(self.get_parameter("elevator_command_topic").value), 10
        )
        self.mission_cancel_client = self.create_client(
            EmptySrv, str(self.get_parameter("mission_cancel_service").value)
        )
        self.goal_sub = self.create_subscription(
            String, str(self.get_parameter("goal_topic").value), self.on_floor_goal, 10
        )
        self.arrived_sub = self.create_subscription(
            Empty,
            str(self.get_parameter("arrived_topic").value),
            self.on_transfer_arrived,
            10,
        )
        self.lobby_ready_sub = self.create_subscription(
            Empty,
            str(self.get_parameter("elevator_lobby_ready_topic").value),
            self.on_elevator_lobby_ready,
            10,
        )
        self.elevator_entered_sub = self.create_subscription(
            Empty,
            str(self.get_parameter("elevator_entered_topic").value),
            self.on_elevator_entered,
            10,
        )
        self.elevator_exited_sub = self.create_subscription(
            Empty,
            str(self.get_parameter("elevator_exited_topic").value),
            self.on_elevator_exited,
            10,
        )
        self.elevator_status_sub = self.create_subscription(
            String,
            str(self.get_parameter("elevator_status_topic").value),
            self.on_elevator_status,
            10,
        )
        self.cancel_sub = self.create_subscription(
            Empty, str(self.get_parameter("cancel_topic").value), self.on_cancel, 10
        )

        self.state = load_floor_state(self.state_file)
        if (
            self.state.state not in {"idle", "canceled", "switching_map"}
            and self.state.current_floor_id
            and self.state.current_floor_id != self.building.current_floor_id
        ):
            self.get_logger().warn(
                "discarding stale multi-floor state: "
                f"state_floor={self.state.current_floor_id} current_floor={self.building.current_floor_id}"
            )
            self.state = FloorMissionState(
                state="idle",
                instruction="已清理与当前地图不匹配的跨楼层残留任务",
            )
            dump_floor_state(self.state_file, self.state)
        self.publish_status(self.state if self.state.state != "idle" else FloorMissionState())
        self._recover_timer = self.create_timer(
            float(self.get_parameter("recover_delay").value), self.recover_after_restart
        )
        self.get_logger().info(
            f"multi-floor manager ready | config={self.building_config_file} current_floor_id={self.building.current_floor_id}"
        )

    def publish_status(self, state: FloorMissionState) -> None:
        self.state = state
        msg = String()
        msg.data = make_status_json(state)
        self.status_pub.publish(msg)
        self.get_logger().info(msg.data)

    def persist_and_publish(self, state: FloorMissionState) -> None:
        state = FloorMissionState(**{**state.__dict__, "updated_at": time.time()})
        dump_floor_state(self.state_file, state)
        self.publish_status(state)

    def publish_single_floor_goal(self, destination_id: str) -> None:
        msg = String()
        msg.data = destination_id
        self.single_floor_goal_pub.publish(msg)
        self.get_logger().info(f"forward single-floor destination: {destination_id}")

    def cancel_current_navigation(self) -> None:
        if self.mission_cancel_client.service_is_ready():
            self.mission_cancel_client.call_async(EmptySrv.Request())

    def publish_elevator_command(self, command: str, floor_id: str) -> None:
        msg = String()
        msg.data = make_elevator_command(command, self.state.elevator_id, floor_id)
        self.elevator_command_pub.publish(msg)
        self.get_logger().info(f"elevator command: {msg.data}")

    def on_floor_goal(self, msg: String) -> None:
        query = msg.data.strip()
        if not query:
            self.persist_and_publish(
                FloorMissionState(state="failed", error="empty floor goal")
            )
            return
        try:
            plan = plan_floor_mission(self.building, query)
        except (KeyError, ValueError) as exc:
            self.persist_and_publish(
                FloorMissionState(
                    state="failed",
                    requested_destination_id=query,
                    error=str(exc),
                    instruction="目的地不存在或多层配置不完整",
                )
            )
            return

        base_state = FloorMissionState(
            requested_destination_id=plan.requested_destination_id,
            current_floor_id=plan.current_floor_id,
            target_floor_id=plan.target_floor_id,
            elevator_id=plan.elevator_id,
            elevator_entry_destination_id=plan.elevator_entry_destination_id,
            final_destination_id=plan.final_destination_id,
            target_map=plan.target_map,
        )
        if not plan.is_cross_floor:
            self.persist_and_publish(
                FloorMissionState(
                    **{
                        **base_state.__dict__,
                        "state": "going_to_destination",
                        "instruction": "同楼层任务，正在前往目的地",
                    }
                )
            )
            self.publish_single_floor_goal(plan.final_destination_id)
            return

        self.persist_and_publish(
            FloorMissionState(
                **{
                    **base_state.__dict__,
                    "state": "going_to_elevator",
                    "instruction": "正在前往当前楼层电梯入口",
                }
            )
        )
        self.publish_single_floor_goal(plan.elevator_entry_destination_id)

    def on_elevator_lobby_ready(self, _msg: Empty) -> None:
        if self.state.state != "going_to_elevator":
            self.publish_status(self.state)
            return
        self.cancel_current_navigation()
        self.persist_and_publish(
            FloorMissionState(
                **{
                    **self.state.__dict__,
                    "state": "waiting_elevator",
                    "instruction": "已到电梯等候点，等待轿厢到达并开门",
                }
            )
        )
        self.publish_elevator_command("call", self.state.current_floor_id)

    def on_elevator_status(self, msg: String) -> None:
        try:
            status = parse_elevator_status(msg.data)
        except (json.JSONDecodeError, ValueError) as exc:
            self.get_logger().warn(f"ignored invalid elevator status: {exc}")
            return
        safe_open = (
            status.available
            and status.door == "open"
            and status.car_present
            and status.motion == "stopped"
        )
        if (
            self.state.state == "waiting_elevator"
            and safe_open
            and status.floor_id == self.state.current_floor_id
        ):
            self.persist_and_publish(
                FloorMissionState(
                    **{
                        **self.state.__dict__,
                        "state": "ready_to_enter",
                        "instruction": "电梯已到且门已打开，请确认机器人已安全进入",
                    }
                )
            )
            self.publish_elevator_command("hold_door", self.state.current_floor_id)
        elif (
            self.state.state == "riding_elevator"
            and safe_open
            and status.floor_id == self.state.target_floor_id
        ):
            self.persist_and_publish(
                FloorMissionState(
                    **{
                        **self.state.__dict__,
                        "state": "ready_to_exit",
                        "instruction": "目标楼层已到且门已打开，请确认机器人已安全出梯",
                    }
                )
            )
            self.publish_elevator_command("hold_door", self.state.target_floor_id)

    def on_elevator_entered(self, _msg: Empty) -> None:
        if self.state.state != "ready_to_enter":
            self.publish_status(self.state)
            return
        self.persist_and_publish(
            FloorMissionState(
                **{
                    **self.state.__dict__,
                    "state": "riding_elevator",
                    "instruction": "已确认进入电梯，等待目标楼层",
                }
            )
        )
        self.publish_elevator_command("go_to_floor", self.state.target_floor_id)

    def on_elevator_exited(self, _msg: Empty) -> None:
        if self.state.state != "ready_to_exit":
            self.publish_status(self.state)
            return
        self.start_map_switch("已确认安全出梯，正在切换目标楼层地图")

    def start_map_switch(self, instruction: str) -> None:
        self.cancel_current_navigation()
        next_state = FloorMissionState(
            **{
                **self.state.__dict__,
                "state": "switching_map",
                "instruction": instruction,
            }
        )
        self.persist_and_publish(next_state)
        env = os.environ.copy()
        env["RESTART_FOXGLOVE"] = str(self.get_parameter("restart_foxglove").value)
        env["MODE"] = str(self.get_parameter("restart_mode").value)
        env["MAP"] = next_state.target_map
        env["FLOOR_ID"] = next_state.target_floor_id
        env["MULTIFLOOR_CURRENT_FLOOR_ID"] = next_state.target_floor_id
        env["ENABLE_MULTIFLOOR_MANAGER"] = "true"
        subprocess.Popen(
            [str(self.restart_script)],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    def on_transfer_arrived(self, _msg: Empty) -> None:
        if self.state.state not in {
            "going_to_elevator",
            "waiting_floor_transfer",
            "waiting_elevator",
            "ready_to_enter",
            "riding_elevator",
            "ready_to_exit",
        }:
            self.publish_status(self.state)
            return
        self.start_map_switch("兼容确认已收到，正在切换目标楼层地图")

    def recover_after_restart(self) -> None:
        self._recover_timer.cancel()
        state = load_floor_state(self.state_file)
        if state.state != "switching_map" or not state.final_destination_id:
            return
        try:
            plan = plan_floor_mission(self.building, state.requested_destination_id)
        except (KeyError, ValueError) as exc:
            self.persist_and_publish(
                FloorMissionState(
                    **{
                        **state.__dict__,
                        "state": "failed",
                        "error": str(exc),
                        "instruction": "重启后恢复跨楼层任务失败",
                    }
                )
            )
            return
        initialpose = make_initialpose_msg(
            plan.target_exit_initial_pose, frame_id=self.map_frame
        )
        for _ in range(max(1, self.recover_initialpose_count)):
            initialpose.header.stamp = self.get_clock().now().to_msg()
            self.initial_pose_pub.publish(initialpose)
            time.sleep(max(0.05, self.recover_initialpose_period))
        resumed = FloorMissionState(
            **{
                **state.__dict__,
                "state": "going_to_destination",
                "instruction": "目标楼层定位已设置，正在前往目的地",
            }
        )
        self.persist_and_publish(resumed)
        self.publish_single_floor_goal(state.final_destination_id)

    def on_cancel(self, _msg: Empty) -> None:
        self.cancel_current_navigation()
        self.persist_and_publish(
            FloorMissionState(state="canceled", instruction="跨楼层任务已取消")
        )


def main(args=None) -> None:
    rclpy.init(args=args)
    node = DDSMFloorMissionManager()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        node.get_logger().info("multi-floor manager stopped")
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
