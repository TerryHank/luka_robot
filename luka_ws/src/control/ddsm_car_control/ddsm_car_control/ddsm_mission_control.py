#!/usr/bin/env python3
"""Unified mission control for automatic robot tasks."""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

import yaml

import rclpy
from geometry_msgs.msg import PoseStamped, Twist
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, qos_profile_sensor_data
from sensor_msgs.msg import Imu
from std_msgs.msg import Bool, Empty, String
from std_srvs.srv import Empty as EmptySrv
from std_srvs.srv import Trigger

PathLike = Union[str, Path]
VALID_COMMANDS = {"pause", "resume", "cancel"}
TERMINAL_NAV_STATES = {
    "succeeded": "succeeded",
    "success": "succeeded",
    "cancelled": "canceled",
    "canceled": "canceled",
    "failed": "failed",
    "aborted": "failed",
}


@dataclass(frozen=True)
class MissionRecord:
    state: str = "idle"
    task_type: str = ""
    target_id: str = ""
    display_name: str = ""
    route_id: str = ""
    waypoint_index: int = 0
    use_final_approach: bool = False


def parse_control_command(value: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError("mission control command is empty")
    command = text
    if text.startswith("{"):
        document = json.loads(text)
        if not isinstance(document, dict):
            raise ValueError("mission control JSON command must be an object")
        command = str(
            document.get("data") or document.get("command") or document.get("action") or ""
        ).strip()
    command = command.casefold()
    if command not in VALID_COMMANDS:
        raise ValueError(f"unsupported mission control command: {command}")
    return command


def parse_navigation_status_state(value: str) -> Optional[str]:
    text = str(value).strip()
    if not text or not text.startswith("{"):
        return None
    try:
        document = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(document, dict):
        return None
    state = str(document.get("state") or "").strip().casefold()
    failure_code = str(document.get("failure_code") or "").strip().casefold()
    if state in TERMINAL_NAV_STATES:
        return TERMINAL_NAV_STATES[state]
    if failure_code == "cancelled" or failure_code == "canceled":
        return "canceled"
    return None


def dump_mission_record(path: PathLike, record: MissionRecord) -> None:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        yaml.safe_dump(
            {
                "state": record.state,
                "task_type": record.task_type,
                "target_id": record.target_id,
                "display_name": record.display_name,
                "route_id": record.route_id,
                "waypoint_index": int(record.waypoint_index),
                "use_final_approach": bool(record.use_final_approach),
            },
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )


def load_mission_record(path: PathLike) -> MissionRecord:
    source = Path(path).expanduser()
    if not source.exists():
        return MissionRecord()
    data = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return MissionRecord()
    return MissionRecord(
        state=str(data.get("state", "idle")),
        task_type=str(data.get("task_type", "")),
        target_id=str(data.get("target_id", "")),
        display_name=str(data.get("display_name", "")),
        route_id=str(data.get("route_id", "")),
        waypoint_index=int(data.get("waypoint_index", 0)),
        use_final_approach=bool(data.get("use_final_approach", False)),
    )


def should_reject_new_goal(state: str) -> bool:
    return str(state).strip().casefold() == "paused"


class DDSMMissionControl(Node):
    def __init__(self) -> None:
        super().__init__("ddsm_mission_control")
        self.declare_parameter("state_file", "/home/sunrise/luka_ws/src/common/config/mission_state.yaml")
        self.declare_parameter("cmd_vel_topic", "/cmd_vel_nav")
        self.declare_parameter("goal_request_topic", "/hotel/goal_destination")
        self.declare_parameter("navigation_status_topic", "/hotel/navigation_status")
        self.declare_parameter("zero_velocity_seconds", 1.0)
        self.declare_parameter("zero_velocity_hz", 10.0)
        self.declare_parameter("hotel_goal_topic", "/hotel/mission/goal_destination")
        self.declare_parameter("hotel_cancel_topic", "/hotel/cancel")
        self.declare_parameter("patrol_pause_topic", "/patrol/pause")
        self.declare_parameter("patrol_resume_topic", "/patrol/resume")
        self.declare_parameter("patrol_stop_topic", "/patrol/stop")
        self.declare_parameter("home_go_topic", "/home/go")
        self.declare_parameter("home_cancel_topic", "/home/cancel")
        self.declare_parameter("final_goal_topic", "/final_approach/goal_pose")
        self.declare_parameter("final_cancel_service", "/final_approach/cancel")
        self.declare_parameter("base_pause_service", "/base_control/pause_now")
        self.declare_parameter("base_resume_service", "/base_control/resume_now")

        self.state_file = Path(str(self.get_parameter("state_file").value)).expanduser()
        self.zero_velocity_seconds = float(self.get_parameter("zero_velocity_seconds").value)
        self.zero_velocity_hz = float(self.get_parameter("zero_velocity_hz").value)
        self.state = "idle"
        self.gamepad_active = False
        self.follow_active = False
        self.imu_last = None
        self.imu_stamp = None
        self.imu_good_since = None
        self.imu_max_age = 0.8
        self.pending_new_goal = None
        self.record = load_mission_record(self.state_file)

        status_qos = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.status_pub = self.create_publisher(String, "/hotel/mission/status", status_qos)
        self.goal_status_pub = self.create_publisher(String, "/hotel/mission/goal_status", 10)
        self.safety_pub = self.create_publisher(String, "/hotel/mission/safety_status", 10)
        self.create_subscription(Imu, "/imu/data", self.on_imu, qos_profile_sensor_data)
        self.create_service(Trigger, "/hotel/mission/imu_health", self.on_imu_health)
        self.create_timer(0.2, self.check_imu_safety)
        self.create_timer(0.25, self.check_new_goal_timeout)
        self.cmd_pub = self.create_publisher(
            Twist, str(self.get_parameter("cmd_vel_topic").value), 10
        )
        self.hotel_goal_pub = self.create_publisher(
            String, str(self.get_parameter("hotel_goal_topic").value), 10
        )
        self.hotel_cancel_pub = self.create_publisher(
            Empty, str(self.get_parameter("hotel_cancel_topic").value), 10
        )
        self.patrol_pause_pub = self.create_publisher(
            Empty, str(self.get_parameter("patrol_pause_topic").value), 10
        )
        self.patrol_resume_pub = self.create_publisher(
            Empty, str(self.get_parameter("patrol_resume_topic").value), 10
        )
        self.patrol_stop_pub = self.create_publisher(
            Empty, str(self.get_parameter("patrol_stop_topic").value), 10
        )
        self.home_go_pub = self.create_publisher(
            Empty, str(self.get_parameter("home_go_topic").value), 10
        )
        self.home_cancel_pub = self.create_publisher(
            Empty, str(self.get_parameter("home_cancel_topic").value), 10
        )
        self.final_goal_pub = self.create_publisher(
            PoseStamped, str(self.get_parameter("final_goal_topic").value), 10
        )
        self.final_cancel_client = self.create_client(
            EmptySrv, str(self.get_parameter("final_cancel_service").value)
        )
        self.base_pause_client = self.create_client(
            EmptySrv, str(self.get_parameter("base_pause_service").value)
        )
        self.base_resume_client = self.create_client(
            EmptySrv, str(self.get_parameter("base_resume_service").value)
        )
        self.entry_cancel_client = self.create_client(EmptySrv, "/hotel/elevator/entry/cancel_now")
        self.create_subscription(Bool, "/gamepad/enabled", self.on_gamepad_enabled, 10)
        self.create_subscription(Bool, "/person_follow/active", self.on_follow_active, status_qos)

        self.pause_sub = self.create_subscription(Empty, "/hotel/mission/pause", self.on_pause, 10)
        self.resume_sub = self.create_subscription(Empty, "/hotel/mission/resume", self.on_resume, 10)
        self.cancel_sub = self.create_subscription(Empty, "/hotel/mission/cancel", self.on_cancel, 10)
        self.control_sub = self.create_subscription(String, "/hotel/mission/control", self.on_control, 10)
        self.goal_seen_sub = self.create_subscription(
            String,
            str(self.get_parameter("goal_request_topic").value),
            self.on_goal_seen,
            10,
        )
        self.navigation_status_sub = self.create_subscription(
            String,
            str(self.get_parameter("navigation_status_topic").value),
            self.on_navigation_status,
            10,
        )
        self.pause_srv = self.create_service(EmptySrv, "/hotel/mission/pause_now", self.on_pause_service)
        self.resume_srv = self.create_service(EmptySrv, "/hotel/mission/resume_now", self.on_resume_service)
        self.cancel_srv = self.create_service(EmptySrv, "/hotel/mission/cancel_now", self.on_cancel_service)

        self.publish_status("paused" if self.record.state == "paused" else "idle")
        self.get_logger().info(f"DDSM mission control ready | state_file={self.state_file}")

    def publish_status(self, state: str) -> None:
        self.state = state
        msg = String()
        msg.data = state
        self.status_pub.publish(msg)
        self.get_logger().info(f"mission status: {state}")

    def persist(self, *, state: Optional[str] = None) -> None:
        record = MissionRecord(
            state=state or self.state,
            task_type=self.record.task_type,
            target_id=self.record.target_id,
            display_name=self.record.display_name,
            route_id=self.record.route_id,
            waypoint_index=self.record.waypoint_index,
            use_final_approach=self.record.use_final_approach,
        )
        self.record = record
        dump_mission_record(self.state_file, record)

    def publish_zero_velocity_burst(self) -> None:
        twist = Twist()
        count = max(1, int(self.zero_velocity_seconds * self.zero_velocity_hz))
        sleep_s = 1.0 / max(1.0, self.zero_velocity_hz)
        for _ in range(count):
            self.cmd_pub.publish(twist)
            time.sleep(sleep_s)

    def request_base_pause(self) -> None:
        if self.base_pause_client.service_is_ready():
            self.base_pause_client.call_async(EmptySrv.Request())
        else:
            self.get_logger().warn("base pause service is not ready")

    def request_base_resume(self) -> None:
        if self.base_resume_client.service_is_ready():
            self.base_resume_client.call_async(EmptySrv.Request())
        else:
            self.get_logger().warn("base resume service is not ready")

    def soft_cancel_motion(self, *, patrol_stop: bool) -> None:
        empty = Empty()
        self.hotel_cancel_pub.publish(empty)
        if patrol_stop:
            self.patrol_stop_pub.publish(empty)
        else:
            self.patrol_pause_pub.publish(empty)
        self.home_cancel_pub.publish(empty)
        if self.entry_cancel_client.service_is_ready():
            self.entry_cancel_client.call_async(EmptySrv.Request())
        if self.final_cancel_client.service_is_ready():
            self.final_cancel_client.call_async(EmptySrv.Request())

    def on_follow_active(self, msg: Bool) -> None:
        self.follow_active = msg.data
        if msg.data:
            self.cancel_new_goal("视觉跟随已接管，请先退出跟随。")

    def on_gamepad_enabled(self, msg: Bool) -> None:
        active = bool(msg.data)
        rising = active and not self.gamepad_active
        self.gamepad_active = active
        if not rising:
            return
        self.cancel_new_goal("手柄已接管，请松开手柄控制后重试。")
        # Cancel automatic tasks without pausing the physical base: the operator
        # must still be able to drive. Releasing the deadman does not resume.
        if self.state not in {"running", "resuming", "paused"}:
            self.record = MissionRecord(state="paused")
        self.persist(state="paused")
        self.publish_status("paused")
        self.soft_cancel_motion(patrol_stop=False)
        self.get_logger().info("manual takeover: automatic task paused until explicit resume")

    def on_imu(self, msg):
        now = time.monotonic()
        stamp = msg.header.stamp.sec * 1000000000 + msg.header.stamp.nanosec
        age = (self.get_clock().now().nanoseconds - stamp) / 1e9
        valid = msg.angular_velocity_covariance[0] != -1 and all(math.isfinite(v) for v in
            (msg.angular_velocity.x, msg.angular_velocity.y, msg.angular_velocity.z))
        if not valid or not -0.2 <= age <= self.imu_max_age:
            self.imu_last = self.imu_good_since = None
            return
        if self.imu_stamp is not None and stamp <= self.imu_stamp:
            return  # Repeated cached samples cannot keep the guard healthy.
        if self.imu_last is None or now-self.imu_last > self.imu_max_age:
            self.imu_good_since = now
        self.imu_stamp = stamp
        self.imu_last = now-max(0.0, age)

    def imu_fault(self):
        now = time.monotonic()
        if self.imu_last is None or now-self.imu_last > self.imu_max_age:
            return "IMU数据中断或无效，不能启动导航，请检查传感器和定位。"
        if self.imu_good_since is None or now-self.imu_good_since < 0.5:
            return "IMU刚恢复，正在确认数据稳定，请稍后重试。"
        return None

    def on_imu_health(self, request, response):
        fault = self.imu_fault()
        response.success = fault is None
        response.message = fault or "IMU正常，导航传感器保护已就绪。"
        return response

    def safety_feedback(self, message):
        self.safety_pub.publish(String(data=json.dumps({
            "state": "imu_guard", "message": message}, ensure_ascii=False)))
        self.get_logger().warn(message)

    def check_imu_safety(self):
        fault = self.imu_fault()
        if fault is None:
            return  # Recovery alone never resumes a paused mission.
        if self.pending_new_goal is not None:
            self.cancel_new_goal(fault)
        if self.state in {"running", "resuming"} and not self.gamepad_active and not self.follow_active:
            self.on_pause(Empty())
            self.safety_feedback("IMU数据异常，导航已进入暂停，已发送停车请求。请检查传感器和定位后，再明确恢复任务。")

    def on_goal_seen(self, msg: String) -> None:
        text = msg.data.strip()
        if not text:
            return
        if self.follow_active:
            self.goal_feedback(text, "rejected", "正在视觉跟随，请先退出跟随，再下达导航指令。")
            return
        if self.gamepad_active:
            self.goal_feedback(text, "rejected", "手柄正在控制小车，请松开手柄控制后重试。")
            return
        if self.pending_new_goal is not None or self.state in {"running", "resuming", "canceling"}:
            self.goal_feedback(text, "rejected", "当前任务尚未结束，请先停止，再下达新导航指令。")
            return
        fault = self.imu_fault()
        if fault:
            self.goal_feedback(text, "rejected", fault)
            return
        if self.hotel_goal_pub.get_subscription_count() == 0:
            self.goal_feedback(text, "rejected", "导航执行服务尚未就绪，请稍后重试。")
            return
        if not self.base_resume_client.service_is_ready():
            self.goal_feedback(text, "rejected", "底盘恢复服务未就绪，未启动导航。")
            return
        # Also clear a base pause left behind by pause->cancel. A fresh explicit
        # destination must NEVER replay the previous destination.
        pending = {"target": text, "deadline": time.monotonic()+3.0, "state": self.state}
        self.pending_new_goal = pending
        try:
            future = self.base_resume_client.call_async(EmptySrv.Request())
            future.add_done_callback(lambda f: self.finish_new_goal(f, pending))
        except Exception:
            self.cancel_new_goal("底盘恢复失败，未启动导航，请重试。")

    def goal_feedback(self, target, state, message):
        self.goal_status_pub.publish(String(data=json.dumps({
            "destination_id": target, "state": state, "message": message}, ensure_ascii=False)))

    def cancel_new_goal(self, reason):
        pending, self.pending_new_goal = self.pending_new_goal, None
        if pending is not None:
            self.goal_feedback(pending["target"], "rejected", reason)

    def check_new_goal_timeout(self):
        if self.pending_new_goal and time.monotonic() > self.pending_new_goal["deadline"]:
            self.cancel_new_goal("等待底盘恢复超时，未启动导航，请重试。")

    def finish_new_goal(self, future, pending):
        if self.pending_new_goal is not pending:
            return
        if time.monotonic() > pending["deadline"]:
            self.check_new_goal_timeout()
            return
        try:
            future.result()
        except Exception:
            self.cancel_new_goal("底盘恢复失败，未启动导航，请重试。")
            return
        if self.gamepad_active or self.follow_active or self.state != pending["state"]:
            self.cancel_new_goal("控制状态已变化，未启动导航，请重新下达指令。")
            return
        fault = self.imu_fault()
        if fault:
            self.cancel_new_goal(fault)
            return
        self.pending_new_goal = None
        self.forward_new_goal(pending["target"])

    def forward_new_goal(self, text):
        self.record = MissionRecord(state="running", task_type="named_destination", target_id=text)
        self.persist(state="running")
        self.publish_status("running")
        self.hotel_goal_pub.publish(String(data=text))
        self.goal_feedback(text, "accepted", "导航请求已接收，等待导航执行结果。")

    def on_navigation_status(self, msg: String) -> None:
        # Cancellation acknowledgements from a paused/cleared task are late
        # results, not permission to overwrite the operator's pause decision.
        if self.state in {"paused", "canceling", "canceled"}:
            return
        terminal_state = parse_navigation_status_state(msg.data)
        if terminal_state is None:
            return
        if self.state == terminal_state:
            return
        self.persist(state=terminal_state)
        self.publish_status(terminal_state)

    def on_pause(self, _msg: Empty) -> None:
        self.cancel_new_goal("任务已暂停，未启动新导航。")
        if self.state == "paused":
            self.publish_status("paused")
            return
        self.request_base_pause()
        self.soft_cancel_motion(patrol_stop=False)
        self.publish_zero_velocity_burst()
        self.persist(state="paused")
        self.publish_status("paused")

    def on_resume(self, _msg: Empty) -> None:
        if self.pending_new_goal is not None:
            return
        if self.gamepad_active or self.follow_active:
            self.get_logger().warn("release gamepad before resuming automatic motion")
            return
        if self.state != "paused":
            self.publish_status(self.state)
            return
        fault = self.imu_fault()
        if fault:
            self.safety_feedback(fault)
            return
        if self.record.task_type == "named_destination" and self.record.target_id:
            # Explicit resume uses the same checked, acknowledged path as a
            # new named goal, not a fire-and-forget base release.
            self.on_goal_seen(String(data=self.record.target_id))
            return
        self.request_base_resume()
        self.publish_status("resuming")
        if not self.record.task_type:
            self.publish_status("idle")
            return
        if self.record.task_type == "named_destination" and self.record.target_id:
            msg = String()
            msg.data = self.record.target_id
            self.hotel_goal_pub.publish(msg)
            self.persist(state="running")
            self.publish_status("running")
            return
        if self.record.task_type == "patrol":
            self.patrol_resume_pub.publish(Empty())
            self.persist(state="running")
            self.publish_status("running")
            return
        if self.record.task_type == "home":
            self.home_go_pub.publish(Empty())
            self.persist(state="running")
            self.publish_status("running")
            return
        self.publish_status("failed")

    def on_cancel(self, _msg: Empty) -> None:
        self.cancel_new_goal("任务已取消，未启动新导航。")
        self.publish_status("canceling")
        self.soft_cancel_motion(patrol_stop=True)
        self.publish_zero_velocity_burst()
        self.record = MissionRecord(state="canceled")
        dump_mission_record(self.state_file, self.record)
        self.publish_status("canceled")

    def on_control(self, msg: String) -> None:
        try:
            command = parse_control_command(msg.data)
        except ValueError as exc:
            self.get_logger().warn(str(exc))
            self.publish_status("failed")
            return
        if command == "pause":
            self.on_pause(Empty())
        elif command == "resume":
            self.on_resume(Empty())
        else:
            self.on_cancel(Empty())

    def on_pause_service(self, _request, response):
        self.on_pause(Empty())
        return response

    def on_resume_service(self, _request, response):
        self.on_resume(Empty())
        return response

    def on_cancel_service(self, _request, response):
        self.on_cancel(Empty())
        return response


def main(args=None) -> None:
    rclpy.init(args=args)
    node = DDSMMissionControl()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    except Exception:
        if rclpy.ok():
            raise
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
