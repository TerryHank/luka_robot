#!/usr/bin/env python3
import json
import math
import time
from dataclasses import dataclass
from typing import Dict, Optional

import rclpy
from geometry_msgs.msg import Quaternion, TransformStamped, Twist
from nav_msgs.msg import Odometry
from rclpy.node import Node
from sensor_msgs.msg import Imu
from std_msgs.msg import String
from std_srvs.srv import Empty as EmptySrv
from tf2_ros import TransformBroadcaster

from .zdt_mecanum_kinematics import (
    MecanumGeometry,
    apply_lateral_hardware_direction,
    clamp,
    clamp_planar_velocity,
    motor_delta_degrees_to_body_delta,
    normalize_motor_directions,
    scale_body_twist,
    twist_to_motor_rpm,
    unwrap_degrees,
)
from .zdt_y42_protocol import ZDTMotorFeedback, ZDTY42SerialBus


def normalize_angle(angle: float) -> float:
    wrapped = (angle + math.pi) % (2.0 * math.pi) - math.pi
    if wrapped == -math.pi:
        return math.pi
    return wrapped


def shortest_angular_error(target_yaw: float, current_yaw: float) -> float:
    return normalize_angle(target_yaw - current_yaw)


def yaw_from_quaternion(quat) -> float:
    return math.atan2(
        2.0 * (quat.w * quat.z + quat.x * quat.y),
        1.0 - 2.0 * (quat.y * quat.y + quat.z * quat.z),
    )


def yaw_to_quaternion(yaw: float) -> Quaternion:
    quat = Quaternion()
    half = yaw * 0.5
    quat.x = 0.0
    quat.y = 0.0
    quat.z = math.sin(half)
    quat.w = math.cos(half)
    return quat


@dataclass
class HeadingPIDConfig:
    enabled: bool = True
    feedback_source: str = "imu"
    kp: float = 0.45
    ki: float = 0.0
    kd: float = 0.0
    max_wz: float = 0.08
    max_integral: float = 0.05
    min_linear_speed: float = 0.03
    angular_deadband: float = 0.02
    max_feedback_age: float = 0.5


@dataclass(frozen=True)
class SelectedVelocityCommand:
    command: Optional[Twist]
    source: str
    age_s: float


@dataclass
class OdomEstimate:
    seq: int = 0
    x: float = 0.0
    y: float = 0.0
    yaw: float = 0.0
    vx: float = 0.0
    vy: float = 0.0
    wz: float = 0.0


def integrate_body_twist(
    odom: OdomEstimate,
    vx: float,
    vy: float,
    wz: float,
    dt: float,
) -> None:
    dt = max(float(dt), 0.0)
    dx_body = float(vx) * dt
    dy_body = float(vy) * dt
    dyaw = float(wz) * dt
    yaw_mid = odom.yaw + 0.5 * dyaw
    odom.x += dx_body * math.cos(yaw_mid) - dy_body * math.sin(yaw_mid)
    odom.y += dx_body * math.sin(yaw_mid) + dy_body * math.cos(yaw_mid)
    odom.yaw = normalize_angle(odom.yaw + dyaw)
    odom.vx = float(vx)
    odom.vy = float(vy)
    odom.wz = float(wz)
    odom.seq += 1


class HeadingPID:
    def __init__(self, config: HeadingPIDConfig) -> None:
        self.config = config
        self.integral = 0.0
        self.previous_error: Optional[float] = None

    def reset(self) -> None:
        self.integral = 0.0
        self.previous_error = None

    def update(self, error: float, dt: float) -> float:
        dt = max(float(dt), 1e-3)
        self.integral = clamp(
            self.integral + error * dt,
            -self.config.max_integral,
            self.config.max_integral,
        )
        derivative = 0.0
        if self.previous_error is not None:
            derivative = (error - self.previous_error) / dt
        self.previous_error = error

        output = (
            self.config.kp * error
            + self.config.ki * self.integral
            + self.config.kd * derivative
        )
        return clamp(output, -self.config.max_wz, self.config.max_wz)


def select_velocity_command(
    manual_cmd: Optional[Twist],
    manual_age_s: float,
    nav_cmd: Optional[Twist],
    nav_age_s: float,
    manual_timeout_s: float,
    nav_timeout_s: float,
) -> SelectedVelocityCommand:
    if manual_cmd is not None and manual_age_s <= manual_timeout_s:
        return SelectedVelocityCommand(manual_cmd, "cmd_vel", manual_age_s)
    if nav_cmd is not None and nav_age_s <= nav_timeout_s:
        return SelectedVelocityCommand(nav_cmd, "cmd_vel_nav", nav_age_s)
    if manual_cmd is not None:
        return SelectedVelocityCommand(None, "timeout_stop", manual_age_s)
    if nav_cmd is not None:
        return SelectedVelocityCommand(None, "timeout_stop", nav_age_s)
    return SelectedVelocityCommand(None, "no_cmd", 0.0)


def parse_motor_ids(value) -> list[int]:
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("[") and text.endswith("]"):
            text = text[1:-1]
        return [int(part.strip()) for part in text.split(",") if part.strip()]
    return [int(item) for item in value]


def build_odom_transform(
    odom: OdomEstimate,
    stamp,
    odom_frame_id: str,
    base_frame_id: str,
) -> TransformStamped:
    transform = TransformStamped()
    transform.header.stamp = stamp
    transform.header.frame_id = odom_frame_id
    transform.child_frame_id = base_frame_id
    transform.transform.translation.x = odom.x
    transform.transform.translation.y = odom.y
    transform.transform.translation.z = 0.0
    transform.transform.rotation = yaw_to_quaternion(odom.yaw)
    return transform


class ZDTMecanumRS485Bridge(Node):
    def __init__(self) -> None:
        super().__init__("zdt_mecanum_rs485_bridge")

        self.declare_parameter("serial_port", "/dev/ttyUSB_RS485")
        self.declare_parameter("baudrate", 115200)
        self.declare_parameter("serial_timeout", 0.03)
        self.declare_parameter("protocol", "modbus")
        self.declare_parameter("firmware", "emm")
        self.declare_parameter("modbus_ack_writes", True)
        self.declare_parameter("free_ack_writes", True)
        self.declare_parameter("motor_ids", [1, 2, 3, 4])
        self.declare_parameter("motor_direction_1", 1)
        self.declare_parameter("motor_direction_2", -1)
        self.declare_parameter("motor_direction_3", 1)
        self.declare_parameter("motor_direction_4", -1)
        self.declare_parameter("wheel_diameter", 0.1016)
        self.declare_parameter("wheel_base", 0.310)
        self.declare_parameter("track_width", 0.355)
        self.declare_parameter("motor_gear_ratio", 1.0)
        self.declare_parameter("cmd_freq", 20.0)
        self.declare_parameter("feedback_freq", 20.0)
        self.declare_parameter("timeout", 0.4)
        self.declare_parameter("manual_override_timeout", 0.5)
        self.declare_parameter("manual_cmd_vel_topic", "cmd_vel")
        self.declare_parameter("nav_cmd_vel_topic", "cmd_vel_nav")
        self.declare_parameter("max_linear_speed", 0.3)
        self.declare_parameter("max_angular_speed", 1.0)
        self.declare_parameter("max_motor_rpm", 300.0)
        self.declare_parameter("mecanum_forward_scale", 1.0)
        self.declare_parameter("mecanum_lateral_scale", 1.0)
        self.declare_parameter("mecanum_lateral_direction", 1)
        self.declare_parameter("mecanum_angular_direction", -1)
        self.declare_parameter("mecanum_angular_scale", 1.0)
        self.declare_parameter("acceleration", 0)
        self.declare_parameter("sync_motion", True)
        self.declare_parameter("feedback_enabled", True)
        self.declare_parameter("read_speed_feedback", False)
        self.declare_parameter("position_wrap_degrees", 0.0)
        self.declare_parameter("odom_frame_id", "odom")
        self.declare_parameter("base_frame_id", "base_link")
        self.declare_parameter("publish_odom", True)
        self.declare_parameter("publish_tf", True)
        self.declare_parameter("data_chain_topic", "ddsm/data_chain")
        self.declare_parameter("imu_topic", "/imu/data")
        self.declare_parameter("heading_pid_enabled", True)
        self.declare_parameter("heading_feedback_source", "imu")
        self.declare_parameter("heading_pid_kp", 0.45)
        self.declare_parameter("heading_pid_ki", 0.0)
        self.declare_parameter("heading_pid_kd", 0.0)
        self.declare_parameter("heading_pid_max_wz", 0.08)
        self.declare_parameter("heading_pid_max_integral", 0.05)
        self.declare_parameter("heading_hold_min_vx", 0.03)
        self.declare_parameter("heading_hold_angular_deadband", 0.02)
        self.declare_parameter("heading_pid_max_feedback_age", 0.5)

        self.serial_port = str(self.get_parameter("serial_port").value)
        self.baudrate = int(self.get_parameter("baudrate").value)
        self.serial_timeout = float(self.get_parameter("serial_timeout").value)
        self.protocol = str(self.get_parameter("protocol").value).strip().lower()
        self.firmware = str(self.get_parameter("firmware").value).strip().lower()
        self.modbus_ack_writes = bool(
            self.get_parameter("modbus_ack_writes").value
        )
        self.free_ack_writes = bool(self.get_parameter("free_ack_writes").value)
        self.motor_ids = parse_motor_ids(self.get_parameter("motor_ids").value)
        if len(self.motor_ids) != 4:
            raise ValueError("motor_ids must contain four motor addresses")
        self.id_by_corner = {
            1: self.motor_ids[0],
            2: self.motor_ids[1],
            3: self.motor_ids[2],
            4: self.motor_ids[3],
        }
        self.corner_by_id = {
            address: corner for corner, address in self.id_by_corner.items()
        }
        self.motor_directions = normalize_motor_directions(
            {
                1: int(self.get_parameter("motor_direction_1").value),
                2: int(self.get_parameter("motor_direction_2").value),
                3: int(self.get_parameter("motor_direction_3").value),
                4: int(self.get_parameter("motor_direction_4").value),
            }
        )
        self.geometry = MecanumGeometry(
            wheel_diameter_m=float(self.get_parameter("wheel_diameter").value),
            wheel_base_m=float(self.get_parameter("wheel_base").value),
            track_width_m=float(self.get_parameter("track_width").value),
            motor_gear_ratio=float(self.get_parameter("motor_gear_ratio").value),
        )
        if self.geometry.motor_gear_ratio <= 0.0:
            raise ValueError("motor_gear_ratio must be positive")

        cmd_freq = float(self.get_parameter("cmd_freq").value)
        feedback_freq = float(self.get_parameter("feedback_freq").value)
        self.timeout = float(self.get_parameter("timeout").value)
        self.manual_override_timeout = float(
            self.get_parameter("manual_override_timeout").value
        )
        self.manual_cmd_vel_topic = str(
            self.get_parameter("manual_cmd_vel_topic").value
        )
        self.nav_cmd_vel_topic = str(self.get_parameter("nav_cmd_vel_topic").value)
        self.max_linear_speed = float(self.get_parameter("max_linear_speed").value)
        self.max_angular_speed = float(self.get_parameter("max_angular_speed").value)
        self.max_motor_rpm = float(self.get_parameter("max_motor_rpm").value)
        self.mecanum_forward_scale = max(
            float(self.get_parameter("mecanum_forward_scale").value), 0.0
        )
        self.mecanum_lateral_scale = max(
            float(self.get_parameter("mecanum_lateral_scale").value), 0.0
        )
        self.mecanum_lateral_direction = (
            -1.0
            if float(self.get_parameter("mecanum_lateral_direction").value) < 0.0
            else 1.0
        )
        self.mecanum_angular_direction = (
            -1.0
            if float(self.get_parameter("mecanum_angular_direction").value) < 0.0
            else 1.0
        )
        self.mecanum_angular_scale = max(
            float(self.get_parameter("mecanum_angular_scale").value), 0.0
        )
        self.acceleration = int(self.get_parameter("acceleration").value)
        if self.acceleration <= 0:
            self.acceleration = 1000 if self.firmware == "x" else 10
        self.sync_motion = bool(self.get_parameter("sync_motion").value)
        self.feedback_enabled = bool(self.get_parameter("feedback_enabled").value)
        self.read_speed_feedback = bool(self.get_parameter("read_speed_feedback").value)
        self.position_wrap_degrees = float(
            self.get_parameter("position_wrap_degrees").value
        )
        self.odom_frame_id = str(self.get_parameter("odom_frame_id").value)
        self.base_frame_id = str(self.get_parameter("base_frame_id").value)
        self.publish_odom = bool(self.get_parameter("publish_odom").value)
        self.publish_tf = bool(self.get_parameter("publish_tf").value)
        self.data_chain_topic = str(self.get_parameter("data_chain_topic").value)
        self.imu_topic = str(self.get_parameter("imu_topic").value)

        heading_feedback_source = str(
            self.get_parameter("heading_feedback_source").value
        ).strip().lower()
        if heading_feedback_source not in {"imu", "odom"}:
            self.get_logger().warn(
                f"unsupported heading_feedback_source={heading_feedback_source!r}; "
                "falling back to imu"
            )
            heading_feedback_source = "imu"
        self.heading_pid_config = HeadingPIDConfig(
            enabled=bool(self.get_parameter("heading_pid_enabled").value),
            feedback_source=heading_feedback_source,
            kp=float(self.get_parameter("heading_pid_kp").value),
            ki=float(self.get_parameter("heading_pid_ki").value),
            kd=float(self.get_parameter("heading_pid_kd").value),
            max_wz=float(self.get_parameter("heading_pid_max_wz").value),
            max_integral=float(self.get_parameter("heading_pid_max_integral").value),
            min_linear_speed=float(self.get_parameter("heading_hold_min_vx").value),
            angular_deadband=float(
                self.get_parameter("heading_hold_angular_deadband").value
            ),
            max_feedback_age=float(
                self.get_parameter("heading_pid_max_feedback_age").value
            ),
        )

        self.bus: Optional[ZDTY42SerialBus] = None
        self.last_connect_attempt_s = 0.0
        self.latest_manual_cmd: Optional[Twist] = None
        self.last_manual_cmd_time = self.get_clock().now()
        self.latest_nav_cmd: Optional[Twist] = None
        self.last_nav_cmd_time = self.get_clock().now()
        self.motion_paused = False
        self.latest_imu_yaw: Optional[float] = None
        self.latest_imu_time = None
        self.odom = OdomEstimate()
        self.latest_odom_time = None
        self.previous_motor_positions: Optional[Dict[int, float]] = None
        self.current_motor_rpm = {corner: 0 for corner in (1, 2, 3, 4)}
        self.latest_feedback_by_corner: Dict[int, ZDTMotorFeedback] = {}
        self.last_send_error = ""
        self.last_feedback_error = ""
        self.last_command_source = "no_cmd"
        self.last_command_age_s = 0.0
        self.last_cmd_input_vx = 0.0
        self.last_cmd_input_vy = 0.0
        self.last_cmd_input_wz = 0.0
        self.last_sent_vx = 0.0
        self.last_sent_vy = 0.0
        self.last_sent_wz = 0.0
        self.last_odom_vx = 0.0
        self.last_odom_vy = 0.0
        self.last_odom_wz = 0.0
        self.last_motor_rpm_log_s = 0.0
        self.heading_pid = HeadingPID(self.heading_pid_config)
        self.heading_target_yaw: Optional[float] = None
        self.last_heading_pid_time = None
        self.last_heading_pid_diag = self._make_heading_pid_diag(False, "startup")

        self.manual_cmd_sub = self.create_subscription(
            Twist, self.manual_cmd_vel_topic, self.on_manual_cmd_vel, 10
        )
        self.nav_cmd_sub = self.create_subscription(
            Twist, self.nav_cmd_vel_topic, self.on_nav_cmd_vel, 10
        )
        self.imu_sub = self.create_subscription(Imu, self.imu_topic, self.on_imu, 50)
        self.odom_pub = self.create_publisher(Odometry, "odom", 10)
        self.data_chain_pub = self.create_publisher(String, self.data_chain_topic, 10)
        self.tf_broadcaster = TransformBroadcaster(self) if self.publish_tf else None
        self.command_timer = self.create_timer(
            1.0 / max(cmd_freq, 1.0),
            self.on_command_timer,
        )
        self.feedback_timer = None
        if self.feedback_enabled:
            self.feedback_timer = self.create_timer(
                1.0 / max(feedback_freq, 1.0),
                self.on_feedback_timer,
            )
        self.base_pause_srv = self.create_service(
            EmptySrv, "/base_control/pause_now", self.on_base_pause
        )
        self.base_resume_srv = self.create_service(
            EmptySrv, "/base_control/resume_now", self.on_base_resume
        )

        self.get_logger().info(
            "ZDT Y42 mecanum RS485 bridge ready | "
            f"port={self.serial_port} baudrate={self.baudrate} "
            f"protocol={self.protocol} firmware={self.firmware} "
            f"motor_ids={self.motor_ids} directions={self.motor_directions} "
            f"cmd_freq={cmd_freq:.1f}Hz feedback_freq={feedback_freq:.1f}Hz "
            f"feedback_enabled={self.feedback_enabled} "
            f"max_linear={self.max_linear_speed:.2f}m/s "
            f"max_angular={self.max_angular_speed:.2f}rad/s "
            f"motion_scale=(vx:{self.mecanum_forward_scale:.2f}, "
            f"vy:{self.mecanum_lateral_scale:.2f}, "
            f"wz:{self.mecanum_angular_scale:.2f}) "
            f"lateral_direction={self.mecanum_lateral_direction:+.0f} "
            f"angular_direction={self.mecanum_angular_direction:+.0f} "
            f"max_motor_rpm={self.max_motor_rpm:.1f} "
            f"acceleration={self.acceleration}"
        )

    def on_manual_cmd_vel(self, msg: Twist) -> None:
        if self.motion_paused:
            return
        self.latest_manual_cmd = msg
        self.last_manual_cmd_time = self.get_clock().now()

    def on_nav_cmd_vel(self, msg: Twist) -> None:
        if self.motion_paused:
            return
        self.latest_nav_cmd = msg
        self.last_nav_cmd_time = self.get_clock().now()

    def on_imu(self, msg: Imu) -> None:
        self.latest_imu_yaw = yaw_from_quaternion(msg.orientation)
        self.latest_imu_time = self.get_clock().now()

    def _ensure_bus(self) -> bool:
        if self.bus is not None:
            return True
        now_s = time.monotonic()
        if now_s - self.last_connect_attempt_s < 2.0:
            return False
        self.last_connect_attempt_s = now_s
        try:
            self.bus = ZDTY42SerialBus(
                port=self.serial_port,
                baudrate=self.baudrate,
                timeout=self.serial_timeout,
                protocol=self.protocol,
                firmware=self.firmware,
                modbus_ack_writes=self.modbus_ack_writes,
                free_ack_writes=self.free_ack_writes,
            )
            self.last_send_error = ""
            self.last_feedback_error = ""
            self.get_logger().info(f"connected RS485 motor bus on {self.serial_port}")
            return True
        except Exception as exc:
            self.last_send_error = str(exc)
            self.get_logger().warn(
                f"cannot open RS485 motor bus {self.serial_port}: {exc}",
                throttle_duration_sec=5.0,
            )
            return False

    def _mark_bus_failed(self, exc: Exception, field: str) -> None:
        if field == "send":
            self.last_send_error = str(exc)
        else:
            self.last_feedback_error = str(exc)
        if self.bus is not None:
            try:
                self.bus.close()
            except Exception:
                pass
        self.bus = None

    def _make_heading_pid_diag(
        self,
        active: bool,
        reason: str,
        target_yaw: Optional[float] = None,
        current_yaw: Optional[float] = None,
        error: float = 0.0,
        correction_wz: float = 0.0,
        feedback_source: Optional[str] = None,
        feedback_age_s: Optional[float] = None,
    ) -> dict:
        return {
            "enabled": self.heading_pid_config.enabled,
            "active": active,
            "reason": reason,
            "feedback_source": feedback_source
            or self.heading_pid_config.feedback_source,
            "target_yaw": target_yaw,
            "current_yaw": current_yaw,
            "error": error,
            "correction_wz": correction_wz,
            "feedback_age_s": feedback_age_s,
            "kp": self.heading_pid_config.kp,
            "ki": self.heading_pid_config.ki,
            "kd": self.heading_pid_config.kd,
            "max_wz": self.heading_pid_config.max_wz,
        }

    def _reset_heading_hold(self, reason: str) -> None:
        self.heading_target_yaw = None
        self.last_heading_pid_time = None
        self.heading_pid.reset()
        self.last_heading_pid_diag = self._make_heading_pid_diag(False, reason)

    def _get_heading_feedback(self, now) -> tuple[Optional[float], str, Optional[float]]:
        source = self.heading_pid_config.feedback_source
        if source == "imu":
            if self.latest_imu_yaw is None or self.latest_imu_time is None:
                return None, "no_imu", None
            age_s = (now - self.latest_imu_time).nanoseconds / 1e9
            if age_s > self.heading_pid_config.max_feedback_age:
                return None, "stale_imu", age_s
            return self.latest_imu_yaw, "imu", age_s

        if self.latest_odom_time is None:
            return None, "no_odom", None
        age_s = (now - self.latest_odom_time).nanoseconds / 1e9
        if age_s > self.heading_pid_config.max_feedback_age:
            return None, "stale_odom", age_s
        return self.odom.yaw, "odom", age_s

    def _apply_heading_hold(self, vx: float, vy: float, wz: float, now) -> tuple:
        config = self.heading_pid_config
        if not config.enabled:
            self._reset_heading_hold("disabled")
            return vx, vy, wz
        if math.hypot(vx, vy) < config.min_linear_speed:
            self._reset_heading_hold("speed_below_min")
            return vx, vy, wz
        if abs(wz) > config.angular_deadband:
            self._reset_heading_hold("angular_cmd")
            return vx, vy, wz

        current_yaw, feedback_source, feedback_age_s = self._get_heading_feedback(now)
        if current_yaw is None:
            self._reset_heading_hold(feedback_source)
            if feedback_age_s is not None:
                self.last_heading_pid_diag["feedback_age_s"] = round(feedback_age_s, 4)
            return vx, vy, wz

        if self.heading_target_yaw is None:
            self.heading_target_yaw = current_yaw
            self.last_heading_pid_time = now
            self.heading_pid.reset()
            error = 0.0
            correction_wz = 0.0
        else:
            dt = 1e-3
            if self.last_heading_pid_time is not None:
                dt = (now - self.last_heading_pid_time).nanoseconds / 1e9
            self.last_heading_pid_time = now
            error = shortest_angular_error(self.heading_target_yaw, current_yaw)
            correction_wz = self.heading_pid.update(error, dt)

        self.last_heading_pid_diag = self._make_heading_pid_diag(
            True,
            "holding",
            target_yaw=self.heading_target_yaw,
            current_yaw=current_yaw,
            error=error,
            correction_wz=correction_wz,
            feedback_source=feedback_source,
            feedback_age_s=round(feedback_age_s, 4)
            if feedback_age_s is not None
            else None,
        )
        return vx, vy, correction_wz

    def clear_velocity_inputs(self) -> None:
        self.latest_manual_cmd = None
        self.latest_nav_cmd = None
        now = self.get_clock().now()
        self.last_manual_cmd_time = now
        self.last_nav_cmd_time = now

    def send_zero_motor_command(self, source: str) -> None:
        self.current_motor_rpm = {corner: 0 for corner in (1, 2, 3, 4)}
        self.last_command_source = source
        self.last_command_age_s = 0.0
        self.last_cmd_input_vx = 0.0
        self.last_cmd_input_vy = 0.0
        self.last_cmd_input_wz = 0.0
        self.last_sent_vx = 0.0
        self.last_sent_vy = 0.0
        self.last_sent_wz = 0.0
        self._reset_heading_hold(source)
        if not self._ensure_bus():
            return
        rpm_by_address = {
            self.id_by_corner[corner]: rpm
            for corner, rpm in self.current_motor_rpm.items()
        }
        try:
            assert self.bus is not None
            self.bus.set_speeds(
                rpm_by_address,
                acceleration=self.acceleration,
                sync=self.sync_motion,
            )
            self.last_send_error = ""
        except Exception as exc:
            self.get_logger().warn(
                f"failed to send motor speeds: {exc}",
                throttle_duration_sec=2.0,
            )
            self._mark_bus_failed(exc, "send")

    def on_base_pause(self, _request, response):
        self.motion_paused = True
        self.clear_velocity_inputs()
        self.send_zero_motor_command("base_pause")
        self.get_logger().warn("base motion paused; cmd_vel inputs are ignored")
        return response

    def on_base_resume(self, _request, response):
        self.motion_paused = False
        self.clear_velocity_inputs()
        self._reset_heading_hold("base_resume")
        self.get_logger().info("base motion resumed")
        return response

    def on_command_timer(self) -> None:
        now = self.get_clock().now()
        manual_age_s = (
            (now - self.last_manual_cmd_time).nanoseconds / 1e9
            if self.latest_manual_cmd is not None
            else 0.0
        )
        nav_age_s = (
            (now - self.last_nav_cmd_time).nanoseconds / 1e9
            if self.latest_nav_cmd is not None
            else 0.0
        )
        selected = select_velocity_command(
            manual_cmd=self.latest_manual_cmd,
            manual_age_s=manual_age_s,
            nav_cmd=self.latest_nav_cmd,
            nav_age_s=nav_age_s,
            manual_timeout_s=self.manual_override_timeout,
            nav_timeout_s=self.timeout,
        )
        if self.motion_paused:
            selected = SelectedVelocityCommand(None, "base_pause", 0.0)

        if selected.command is None:
            vx = 0.0
            vy = 0.0
            wz = 0.0
            self.last_command_source = selected.source
            self.last_command_age_s = selected.age_s
            self.last_cmd_input_vx = 0.0
            self.last_cmd_input_vy = 0.0
            self.last_cmd_input_wz = 0.0
            self._reset_heading_hold(selected.source)
        else:
            vx = float(selected.command.linear.x)
            vy = float(selected.command.linear.y)
            wz = float(selected.command.angular.z)
            self.last_command_source = selected.source
            self.last_command_age_s = selected.age_s
            self.last_cmd_input_vx = vx
            self.last_cmd_input_vy = vy
            self.last_cmd_input_wz = wz
            vx, vy = clamp_planar_velocity(vx, vy, self.max_linear_speed)
            if self.max_angular_speed > 0.0:
                wz = clamp(wz, -self.max_angular_speed, self.max_angular_speed)
            vx, vy, wz = self._apply_heading_hold(vx, vy, wz, now)
            vx, vy, wz = scale_body_twist(
                vx,
                vy,
                wz,
                forward_scale=self.mecanum_forward_scale,
                lateral_scale=self.mecanum_lateral_scale,
                angular_scale=self.mecanum_angular_scale,
            )

        motor_vx, motor_vy, motor_wz = apply_lateral_hardware_direction(
            vx,
            vy,
            wz,
            self.mecanum_lateral_direction,
        )
        motor_wz *= self.mecanum_angular_direction
        self.last_odom_vx = vx
        self.last_odom_vy = vy
        self.last_odom_wz = wz
        self.last_sent_vx = motor_vx
        self.last_sent_vy = motor_vy
        self.last_sent_wz = motor_wz
        self.current_motor_rpm = twist_to_motor_rpm(
            motor_vx,
            motor_vy,
            motor_wz,
            geometry=self.geometry,
            motor_directions=self.motor_directions,
            max_rpm=self.max_motor_rpm,
        )
        now_s = time.monotonic()
        if now_s - self.last_motor_rpm_log_s >= 1.0:
            self.last_motor_rpm_log_s = now_s
            self.get_logger().info(
                f"cmd source={self.last_command_source} "
                f"vx={vx:.3f} vy={vy:.3f} wz={wz:.3f} "
                f"target_rpm={self.current_motor_rpm}"
            )
        rpm_by_address = {
            self.id_by_corner[corner]: rpm
            for corner, rpm in self.current_motor_rpm.items()
        }

        if not self._ensure_bus():
            return
        try:
            assert self.bus is not None
            self.bus.set_speeds(
                rpm_by_address,
                acceleration=self.acceleration,
                sync=self.sync_motion,
            )
            self.last_send_error = ""
            if not self.feedback_enabled:
                self.publish_command_integrated_odom(now, vx, vy, wz)
                self.publish_data_chain_msg()
        except Exception as exc:
            self.get_logger().warn(
                f"failed to send motor speeds: {exc}",
                throttle_duration_sec=2.0,
            )
            self._mark_bus_failed(exc, "send")

    def publish_command_integrated_odom(
        self,
        now,
        vx: float,
        vy: float,
        wz: float,
    ) -> None:
        if self.latest_odom_time is None:
            self.latest_odom_time = now
            integrate_body_twist(self.odom, vx, vy, wz, 0.0)
        else:
            dt = max((now - self.latest_odom_time).nanoseconds / 1e9, 0.0)
            self.latest_odom_time = now
            integrate_body_twist(self.odom, vx, vy, wz, dt)
        self.publish_odom_msg(now)

    def on_feedback_timer(self) -> None:
        if not self._ensure_bus():
            return
        feedback_by_corner: Dict[int, ZDTMotorFeedback] = {}
        try:
            assert self.bus is not None
            for corner, address in self.id_by_corner.items():
                feedback_by_corner[corner] = self.bus.read_feedback(
                    address,
                    read_speed=self.read_speed_feedback,
                )
        except Exception as exc:
            self.get_logger().warn(
                f"failed to read motor feedback: {exc}",
                throttle_duration_sec=2.0,
            )
            self._mark_bus_failed(exc, "feedback")
            return

        self.latest_feedback_by_corner = feedback_by_corner
        invalid = [
            f"{corner}:{feedback.error}"
            for corner, feedback in feedback_by_corner.items()
            if not feedback.valid or feedback.position_degrees is None
        ]
        if invalid:
            self.last_feedback_error = "; ".join(invalid)
            self.get_logger().warn(
                f"invalid motor feedback: {self.last_feedback_error}",
                throttle_duration_sec=2.0,
            )
            self.previous_motor_positions = None
            now = self.get_clock().now()
            self.publish_command_integrated_odom(
                now,
                self.last_odom_vx,
                self.last_odom_vy,
                self.last_odom_wz,
            )
            self.publish_data_chain_msg()
            return
        self.last_feedback_error = ""

        current_positions = {
            corner: float(feedback.position_degrees)
            for corner, feedback in feedback_by_corner.items()
        }
        now = self.get_clock().now()
        if self.previous_motor_positions is None:
            self.previous_motor_positions = current_positions
            self.latest_odom_time = now
            self.publish_odom_msg(now)
            self.publish_data_chain_msg()
            return

        if self.latest_odom_time is None:
            dt = 1e-3
        else:
            dt = max((now - self.latest_odom_time).nanoseconds / 1e9, 1e-3)
        self.latest_odom_time = now

        motor_delta = {}
        for corner in (1, 2, 3, 4):
            previous = self.previous_motor_positions[corner]
            current = current_positions[corner]
            if self.position_wrap_degrees > 0.0:
                motor_delta[corner] = unwrap_degrees(
                    previous,
                    current,
                    period_degrees=self.position_wrap_degrees,
                )
            else:
                motor_delta[corner] = current - previous
        self.previous_motor_positions = current_positions

        dx_body, dy_body, dyaw = motor_delta_degrees_to_body_delta(
            motor_delta,
            self.geometry,
            self.motor_directions,
        )
        dyaw *= self.mecanum_angular_direction
        yaw_mid = self.odom.yaw + 0.5 * dyaw
        self.odom.x += dx_body * math.cos(yaw_mid) - dy_body * math.sin(yaw_mid)
        self.odom.y += dx_body * math.sin(yaw_mid) + dy_body * math.cos(yaw_mid)
        self.odom.yaw = normalize_angle(self.odom.yaw + dyaw)
        self.odom.vx = dx_body / dt
        self.odom.vy = dy_body / dt
        self.odom.wz = dyaw / dt
        self.odom.seq += 1

        self.publish_odom_msg(now)
        self.publish_data_chain_msg()

    def publish_odom_msg(self, now) -> None:
        if not self.publish_odom:
            return
        stamp = now.to_msg()
        msg = Odometry()
        msg.header.stamp = stamp
        msg.header.frame_id = self.odom_frame_id
        msg.child_frame_id = self.base_frame_id
        msg.pose.pose.position.x = self.odom.x
        msg.pose.pose.position.y = self.odom.y
        msg.pose.pose.position.z = 0.0
        msg.pose.pose.orientation = yaw_to_quaternion(self.odom.yaw)
        msg.twist.twist.linear.x = self.odom.vx
        msg.twist.twist.linear.y = self.odom.vy
        msg.twist.twist.angular.z = self.odom.wz

        msg.pose.covariance[0] = 0.03
        msg.pose.covariance[7] = 0.05
        msg.pose.covariance[35] = 0.08
        msg.twist.covariance[0] = 0.03
        msg.twist.covariance[7] = 0.05
        msg.twist.covariance[35] = 0.08
        self.odom_pub.publish(msg)

        if self.tf_broadcaster is not None:
            self.tf_broadcaster.sendTransform(
                build_odom_transform(
                    self.odom,
                    stamp,
                    self.odom_frame_id,
                    self.base_frame_id,
                )
            )

    def _feedback_payload(self) -> list[dict]:
        payload = []
        for corner in (1, 2, 3, 4):
            feedback = self.latest_feedback_by_corner.get(corner)
            if feedback is None:
                payload.append(
                    {
                        "corner": corner,
                        "id": self.id_by_corner[corner],
                        "valid": False,
                        "mode": 0,
                        "torque": 0,
                        "speed_rpm": 0,
                        "position": 0,
                        "total_encoder": 0,
                        "error": 0,
                        "error_text": "no_feedback",
                        "age_ms": 0,
                    }
                )
                continue
            position_degrees = feedback.position_degrees or 0.0
            position_units = int(round(position_degrees * 1000.0))
            age_s = time.monotonic() - feedback.stamp if feedback.stamp else 0.0
            payload.append(
                {
                    "corner": corner,
                    "id": feedback.address,
                    "valid": feedback.valid,
                    "mode": 0,
                    "torque": 0,
                    "position_degrees": feedback.position_degrees,
                    "speed_rpm": 0 if feedback.speed_rpm is None else feedback.speed_rpm,
                    "position": position_units,
                    "total_encoder": position_units,
                    "error": 0 if feedback.valid else 1,
                    "error_text": feedback.error,
                    "age_s": round(age_s, 4),
                    "age_ms": int(round(age_s * 1000.0)),
                }
            )
        return payload

    def publish_data_chain_msg(self) -> None:
        msg = String()
        payload = {
            "ros_cmd_vel_input": {
                "source": self.last_command_source,
                "age_s": round(self.last_command_age_s, 4),
                "vx": self.last_cmd_input_vx,
                "vy": self.last_cmd_input_vy,
                "wz": self.last_cmd_input_wz,
            },
            "bridge_rs485_output": {
                "serial_port": self.serial_port,
                "baudrate": self.baudrate,
                "protocol": self.protocol,
                "firmware": self.firmware,
                "sync_motion": self.sync_motion,
                "acceleration": self.acceleration,
                "vx": self.last_sent_vx,
                "vy": self.last_sent_vy,
                "wz": self.last_sent_wz,
                "target_motor_rpm": [
                    {
                        "corner": corner,
                        "id": self.id_by_corner[corner],
                        "rpm": self.current_motor_rpm[corner],
                    }
                    for corner in (1, 2, 3, 4)
                ],
                "last_send_error": self.last_send_error,
            },
            "heading_pid": self.last_heading_pid_diag,
            "mecanum_inverse_kinematics": {
                "wheel_diameter_m": self.geometry.wheel_diameter_m,
                "wheel_base_m": self.geometry.wheel_base_m,
                "track_width_m": self.geometry.track_width_m,
                "motor_gear_ratio": self.geometry.motor_gear_ratio,
                "motion_scale": {
                    "vx": self.mecanum_forward_scale,
                    "vy": self.mecanum_lateral_scale,
                    "wz": self.mecanum_angular_scale,
                },
                "lateral_direction": self.mecanum_lateral_direction,
                "angular_direction": self.mecanum_angular_direction,
                "corner_order": {
                    "1": "front_left",
                    "2": "front_right",
                    "3": "rear_left",
                    "4": "rear_right",
                },
                "motor_directions": self.motor_directions,
            },
            "motor_feedback_input": {
                "last_feedback_error": self.last_feedback_error,
                "wheels": self._feedback_payload(),
            },
            "mecanum_odometry_method": {
                "source": "ZDT_Y42 realtime motor position over RS485",
                "position_wrap_degrees": self.position_wrap_degrees,
                "integration": "mecanum wheel delta converted to body dx/dy/dyaw, then midpoint yaw integration",
            },
            "esp32_odom_udp_input": {
                "magic": "zdt_rs485",
                "seq": self.odom.seq,
                "stamp_ms": int(time.time() * 1000.0),
                "x": self.odom.x,
                "y": self.odom.y,
                "yaw": self.odom.yaw,
                "vx": self.odom.vx,
                "vy": self.odom.vy,
                "wz": self.odom.wz,
            },
            "ros_odom_output": {
                "topic": "/odom",
                "frame_id": self.odom_frame_id,
                "child_frame_id": self.base_frame_id,
                "seq": self.odom.seq,
                "x": self.odom.x,
                "y": self.odom.y,
                "yaw": self.odom.yaw,
                "vx": self.odom.vx,
                "vy": self.odom.vy,
                "wz": self.odom.wz,
            },
        }
        msg.data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        self.data_chain_pub.publish(msg)

    def destroy_node(self) -> None:
        self.get_logger().info("Stopping ZDT motors and closing RS485 bus...")
        if self.bus is not None:
            try:
                for _ in range(3):
                    for address in self.motor_ids:
                        self.bus.stop_motor(address, sync=False)
                    time.sleep(0.03)
                self.bus.close()
            except Exception as exc:
                self.get_logger().warn(f"failed to send final motor stop: {exc}")
        super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = None
    try:
        node = ZDTMecanumRS485Bridge()
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
