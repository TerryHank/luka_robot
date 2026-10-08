#!/usr/bin/env python3
import json
import math
from dataclasses import dataclass
from typing import Any, Optional

import rclpy
from geometry_msgs.msg import Quaternion, TransformStamped, Twist
from nav_msgs.msg import Odometry
from rclpy.node import Node
from sensor_msgs.msg import Imu
from std_msgs.msg import String
from tf2_ros import TransformBroadcaster

from .ddsm_udp_protocol import DDSMUDPClient, OdomFeedback, SentTwistPacket


TRACK_WIDTH_M = 0.355
WHEEL_DIAMETER_M = 0.1016
MAX_RPM = 200


def clamp_value(value: float, lower: float, upper: float) -> float:
    return min(max(value, lower), upper)


def limit_linear_velocity(
    vx: float,
    vy: float,
    max_linear_speed: float,
) -> tuple[float, float]:
    max_linear_speed = float(max_linear_speed)
    if max_linear_speed <= 0.0:
        return vx, vy

    speed = math.hypot(vx, vy)
    if speed <= max_linear_speed or speed == 0.0:
        return vx, vy

    scale = max_linear_speed / speed
    return vx * scale, vy * scale


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


@dataclass
class HeadingPIDConfig:
    enabled: bool = True
    feedback_source: str = "imu"
    kp: float = 0.45
    ki: float = 0.0
    kd: float = 0.0
    max_wz: float = 0.08
    max_integral: float = 0.05
    min_vx: float = 0.03
    angular_deadband: float = 0.02
    max_feedback_age: float = 0.5


@dataclass(frozen=True)
class SelectedVelocityCommand:
    command: Optional[Any]
    source: str
    age_s: float


def select_velocity_command(
    manual_cmd: Optional[Any],
    manual_age_s: float,
    nav_cmd: Optional[Any],
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
        self.integral = clamp_value(
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
        return clamp_value(output, -self.config.max_wz, self.config.max_wz)


def yaw_to_quaternion(yaw: float) -> Quaternion:
    quat = Quaternion()
    half = yaw * 0.5
    quat.x = 0.0
    quat.y = 0.0
    quat.z = math.sin(half)
    quat.w = math.cos(half)
    return quat


def build_odom_transform(
    feedback: OdomFeedback,
    stamp,
    odom_frame_id: str,
    base_frame_id: str,
) -> TransformStamped:
    transform = TransformStamped()
    if stamp is not None:
        transform.header.stamp = stamp
    transform.header.frame_id = odom_frame_id
    transform.child_frame_id = base_frame_id
    transform.transform.translation.x = feedback.x
    transform.transform.translation.y = feedback.y
    transform.transform.translation.z = 0.0
    transform.transform.rotation = yaw_to_quaternion(feedback.yaw)
    return transform


def lroundf(value: float) -> int:
    if value >= 0.0:
        return int(math.floor(value + 0.5))
    return int(math.ceil(value - 0.5))


def clamp_rpm(value: float) -> int:
    if value > MAX_RPM:
        return MAX_RPM
    if value < -MAX_RPM:
        return -MAX_RPM
    return lroundf(value)


def compute_expected_wheel_targets(vx: float, wz: float) -> list[dict]:
    rpm_factor = 60.0 / (math.pi * WHEEL_DIAMETER_M)
    half_track = TRACK_WIDTH_M * 0.5
    left_rpm = (vx - wz * half_track) * rpm_factor
    right_rpm = (vx + wz * half_track) * rpm_factor
    return [
        {"id": 1, "target_rpm": clamp_rpm(left_rpm)},
        {"id": 2, "target_rpm": clamp_rpm(-right_rpm)},
        {"id": 3, "target_rpm": clamp_rpm(left_rpm)},
        {"id": 4, "target_rpm": clamp_rpm(-right_rpm)},
    ]


def build_data_chain_payload(
    host: str,
    command_port: int,
    command_source: str,
    command_age_s: float,
    sent: SentTwistPacket,
    feedback: OdomFeedback,
    input_vx: Optional[float] = None,
    input_vy: Optional[float] = None,
    input_wz: Optional[float] = None,
    heading_pid: Optional[dict] = None,
) -> str:
    input_vx = sent.vx if input_vx is None else input_vx
    input_vy = sent.vy if input_vy is None else input_vy
    input_wz = sent.wz if input_wz is None else input_wz
    heading_pid = heading_pid or {
        "enabled": False,
        "active": False,
        "reason": "not_configured",
    }

    payload = {
        "ros_cmd_vel_input": {
            "source": command_source,
            "age_s": round(command_age_s, 4),
            "vx": input_vx,
            "vy": input_vy,
            "wz": input_wz,
        },
        "bridge_udp_output": {
            "target_host": host,
            "target_port": command_port,
            "magic": "0xddc2",
            "seq": sent.seq,
            "stamp_ms": sent.stamp_ms,
            "vx": sent.vx,
            "vy": sent.vy,
            "wz": sent.wz,
            "crc": sent.crc,
            "packet_len": sent.packet_len,
            "packet_hex": sent.packet_hex,
        },
        "heading_pid": heading_pid,
        "esp32_inverse_kinematics_expected": {
            "track_width_m": TRACK_WIDTH_M,
            "wheel_diameter_m": WHEEL_DIAMETER_M,
            "wheel_targets_rpm": compute_expected_wheel_targets(sent.vx, sent.wz),
        },
        "esp32_odom_udp_input": {
            "magic": "0xdd52",
            "seq": feedback.seq,
            "stamp_ms": feedback.stamp_ms,
            "x": feedback.x,
            "y": feedback.y,
            "yaw": feedback.yaw,
            "vx": feedback.vx,
            "vy": feedback.vy,
            "wz": feedback.wz,
        },
        "motor_feedback_input": {
            "wheels": [
                {
                    "id": wheel.wheel_id,
                    "valid": wheel.valid,
                    "mode": wheel.mode,
                    "torque": wheel.torque,
                    "speed_rpm": wheel.speed_rpm,
                    "position": wheel.position,
                    "total_encoder": wheel.total_encoder,
                    "error": wheel.error,
                    "age_ms": wheel.age_ms,
                }
                for wheel in feedback.wheels
            ]
        },
        "esp32_odometry_method": {
            "source": "DDSM315 pos",
            "single_turn_counts": 32768,
            "unwrap": "shortest signed delta between adjacent DDSM position samples",
            "integration": "left/right wheel displacement midpoint integration",
        },
        "ros_odom_output": {
            "topic": "/odom",
            "frame_id": "odom",
            "child_frame_id": "base_link",
            "x": feedback.x,
            "y": feedback.y,
            "yaw": feedback.yaw,
            "vx": feedback.vx,
            "vy": feedback.vy,
            "wz": feedback.wz,
        },
        "ros_tf_output": {
            "parent_frame_id": "odom",
            "child_frame_id": "base_link",
            "x": feedback.x,
            "y": feedback.y,
            "yaw": feedback.yaw,
        },
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


class UDPCmdVelBridge(Node):
    def __init__(self) -> None:
        super().__init__("udp_cmd_vel_bridge")

        self.declare_parameter("host", "192.168.3.139")
        self.declare_parameter("command_port", 9001)
        self.declare_parameter("odom_port", 9000)
        self.declare_parameter("cmd_freq", 20.0)
        self.declare_parameter("timeout", 0.4)
        self.declare_parameter("max_linear_speed", 0.3)
        self.declare_parameter("manual_cmd_vel_topic", "cmd_vel")
        self.declare_parameter("nav_cmd_vel_topic", "cmd_vel_nav")
        self.declare_parameter("manual_override_timeout", 0.5)
        self.declare_parameter("imu_topic", "/imu/data")
        self.declare_parameter("odom_frame_id", "odom")
        self.declare_parameter("base_frame_id", "base_link")
        self.declare_parameter("publish_odom", True)
        self.declare_parameter("publish_tf", True)
        self.declare_parameter("heading_pid_enabled", True)
        self.declare_parameter("heading_feedback_source", "imu")
        self.declare_parameter("heading_pid_kp", 0.45)
        self.declare_parameter("heading_pid_ki", 0.0)
        self.declare_parameter("heading_pid_kd", 0.0)
        self.declare_parameter("heading_pid_max_wz", 0.08)
        self.declare_parameter("heading_pid_max_integral", 0.05)
        self.declare_parameter("heading_hold_min_vx", 0.03)
        self.declare_parameter("heading_hold_angular_deadband", 0.02)
        self.declare_parameter("heading_pid_max_odom_age", 0.5)
        legacy_max_feedback_age = float(
            self.get_parameter("heading_pid_max_odom_age").value
        )
        self.declare_parameter("heading_pid_max_feedback_age", legacy_max_feedback_age)

        self.host = self.get_parameter("host").value
        self.command_port = int(self.get_parameter("command_port").value)
        odom_port = int(self.get_parameter("odom_port").value)
        cmd_freq = float(self.get_parameter("cmd_freq").value)
        self.timeout = float(self.get_parameter("timeout").value)
        self.max_linear_speed = float(self.get_parameter("max_linear_speed").value)
        self.manual_cmd_vel_topic = self.get_parameter("manual_cmd_vel_topic").value
        self.nav_cmd_vel_topic = self.get_parameter("nav_cmd_vel_topic").value
        self.manual_override_timeout = float(
            self.get_parameter("manual_override_timeout").value
        )
        self.imu_topic = self.get_parameter("imu_topic").value
        self.odom_frame_id = self.get_parameter("odom_frame_id").value
        self.base_frame_id = self.get_parameter("base_frame_id").value
        self.publish_odom = bool(self.get_parameter("publish_odom").value)
        self.publish_tf = bool(self.get_parameter("publish_tf").value)
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
            min_vx=float(self.get_parameter("heading_hold_min_vx").value),
            angular_deadband=float(
                self.get_parameter("heading_hold_angular_deadband").value
            ),
            max_feedback_age=float(
                self.get_parameter("heading_pid_max_feedback_age").value
            ),
        )

        self.client = DDSMUDPClient(
            self.host,
            command_port=self.command_port,
            odom_port=odom_port,
        )
        self.latest_manual_cmd: Optional[Twist] = None
        self.last_manual_cmd_time = self.get_clock().now()
        self.latest_nav_cmd: Optional[Twist] = None
        self.last_nav_cmd_time = self.get_clock().now()
        self.last_odom_seq: Optional[int] = None
        self.last_sent: Optional[SentTwistPacket] = None
        self.last_command_source = "no_cmd"
        self.last_command_age_s = 0.0
        self.last_cmd_input_vx = 0.0
        self.last_cmd_input_vy = 0.0
        self.last_cmd_input_wz = 0.0
        self.latest_odom: Optional[OdomFeedback] = None
        self.latest_odom_time = None
        self.latest_imu_yaw: Optional[float] = None
        self.latest_imu_time = None
        self.heading_pid = HeadingPID(self.heading_pid_config)
        self.heading_target_yaw: Optional[float] = None
        self.last_heading_pid_time = None
        self.last_heading_pid_diag = self._make_heading_pid_diag(
            active=False,
            reason="startup",
        )

        self.manual_cmd_sub = self.create_subscription(
            Twist, self.manual_cmd_vel_topic, self.on_manual_cmd_vel, 10
        )
        self.nav_cmd_sub = self.create_subscription(
            Twist, self.nav_cmd_vel_topic, self.on_nav_cmd_vel, 10
        )
        self.imu_sub = self.create_subscription(Imu, self.imu_topic, self.on_imu, 50)
        self.odom_pub = self.create_publisher(Odometry, "odom", 10)
        self.data_chain_pub = self.create_publisher(String, "ddsm/data_chain", 10)
        self.tf_broadcaster = None
        if self.publish_tf:
            self.tf_broadcaster = TransformBroadcaster(self)
        self.timer = self.create_timer(1.0 / max(cmd_freq, 1.0), self.on_timer)

        self.get_logger().info(
            f"UDP cmd_vel bridge ready | esp32={self.host}:{self.command_port} "
            f"odom_port={odom_port} cmd_freq={cmd_freq:.1f}Hz timeout={self.timeout:.2f}s "
            f"max_linear_speed={self.max_linear_speed:.2f}m/s "
            f"manual_topic={self.manual_cmd_vel_topic} "
            f"nav_topic={self.nav_cmd_vel_topic} "
            f"manual_override_timeout={self.manual_override_timeout:.2f}s "
            f"heading_feedback={self.heading_pid_config.feedback_source} "
            f"imu_topic={self.imu_topic}"
        )

    def on_manual_cmd_vel(self, msg: Twist) -> None:
        self.latest_manual_cmd = msg
        self.last_manual_cmd_time = self.get_clock().now()

    def on_nav_cmd_vel(self, msg: Twist) -> None:
        self.latest_nav_cmd = msg
        self.last_nav_cmd_time = self.get_clock().now()

    def on_imu(self, msg: Imu) -> None:
        self.latest_imu_yaw = yaw_from_quaternion(msg.orientation)
        self.latest_imu_time = self.get_clock().now()

    def on_timer(self) -> None:
        self.send_latest_command()
        self.drain_odom()

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
        self.last_heading_pid_diag = self._make_heading_pid_diag(
            active=False,
            reason=reason,
        )

    def _get_heading_feedback(self, now) -> tuple[Optional[float], str, Optional[float]]:
        source = self.heading_pid_config.feedback_source
        if source == "imu":
            if self.latest_imu_yaw is None or self.latest_imu_time is None:
                return None, "no_imu", None
            age_s = (now - self.latest_imu_time).nanoseconds / 1e9
            if age_s > self.heading_pid_config.max_feedback_age:
                return None, "stale_imu", age_s
            return self.latest_imu_yaw, "imu", age_s

        if self.latest_odom is None or self.latest_odom_time is None:
            return None, "no_odom", None
        age_s = (now - self.latest_odom_time).nanoseconds / 1e9
        if age_s > self.heading_pid_config.max_feedback_age:
            return None, "stale_odom", age_s
        return self.latest_odom.yaw, "odom", age_s

    def _apply_heading_hold(self, vx: float, vy: float, wz: float, now) -> tuple:
        config = self.heading_pid_config
        if not config.enabled:
            self._reset_heading_hold("disabled")
            return vx, vy, wz
        if abs(vx) < config.min_vx:
            self._reset_heading_hold("vx_below_min")
            return vx, vy, wz
        if abs(wz) > config.angular_deadband:
            self._reset_heading_hold("manual_angular_cmd")
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
            if self.last_heading_pid_time is None:
                dt = 1e-3
            else:
                dt = (now - self.last_heading_pid_time).nanoseconds / 1e9
            self.last_heading_pid_time = now
            error = shortest_angular_error(self.heading_target_yaw, current_yaw)
            correction_wz = self.heading_pid.update(error, dt)

        self.last_heading_pid_diag = self._make_heading_pid_diag(
            active=True,
            reason="holding",
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

    def send_latest_command(self) -> None:
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

        if selected.command is None:
            self.last_command_source = "no_cmd"
            self.last_command_age_s = 0.0
            self.last_cmd_input_vx = 0.0
            self.last_cmd_input_vy = 0.0
            self.last_cmd_input_wz = 0.0
            if selected.source == "timeout_stop":
                self.last_command_source = "timeout_stop"
                self.last_command_age_s = selected.age_s
                self._reset_heading_hold("timeout_stop")
            else:
                self._reset_heading_hold("no_cmd")
            self.last_sent = self.client.send_twist(0.0, 0.0, 0.0)
            return

        self.last_command_source = selected.source
        self.last_command_age_s = selected.age_s
        vx = float(selected.command.linear.x)
        vy = float(selected.command.linear.y)
        wz = float(selected.command.angular.z)
        self.last_cmd_input_vx = vx
        self.last_cmd_input_vy = vy
        self.last_cmd_input_wz = wz
        limited_vx, limited_vy = limit_linear_velocity(
            vx,
            vy,
            self.max_linear_speed,
        )
        send_vx, send_vy, send_wz = self._apply_heading_hold(
            limited_vx,
            limited_vy,
            wz,
            now,
        )
        self.last_sent = self.client.send_twist(send_vx, send_vy, send_wz)

    def drain_odom(self) -> None:
        while True:
            try:
                odom = self.client.recv_odom()
            except ValueError as exc:
                self.get_logger().warn(f"ignored bad odom packet: {exc}", throttle_duration_sec=2.0)
                continue
            if odom is None:
                break
            self.latest_odom = odom
            self.latest_odom_time = self.get_clock().now()
            self.publish_odom_msg(odom)
            self.publish_data_chain_msg(odom)

    def publish_odom_msg(self, feedback: OdomFeedback) -> None:
        if not self.publish_odom:
            return

        msg = Odometry()
        stamp = self.get_clock().now().to_msg()
        msg.header.stamp = stamp
        msg.header.frame_id = self.odom_frame_id
        msg.child_frame_id = self.base_frame_id
        msg.pose.pose.position.x = feedback.x
        msg.pose.pose.position.y = feedback.y
        msg.pose.pose.position.z = 0.0
        msg.pose.pose.orientation = yaw_to_quaternion(feedback.yaw)
        msg.twist.twist.linear.x = feedback.vx
        msg.twist.twist.linear.y = feedback.vy
        msg.twist.twist.angular.z = feedback.wz

        # Conservative diagonal covariance so downstream tools know this is wheel odometry.
        msg.pose.covariance[0] = 0.02
        msg.pose.covariance[7] = 0.02
        msg.pose.covariance[35] = 0.05
        msg.twist.covariance[0] = 0.02
        msg.twist.covariance[7] = 0.02
        msg.twist.covariance[35] = 0.05

        self.odom_pub.publish(msg)
        if self.publish_tf and self.tf_broadcaster is not None:
            self.tf_broadcaster.sendTransform(
                build_odom_transform(
                    feedback,
                    stamp,
                    self.odom_frame_id,
                    self.base_frame_id,
                )
            )
        self.last_odom_seq = feedback.seq

    def publish_data_chain_msg(self, feedback: OdomFeedback) -> None:
        if self.last_sent is None:
            return

        msg = String()
        msg.data = build_data_chain_payload(
            host=self.host,
            command_port=self.command_port,
            command_source=self.last_command_source,
            command_age_s=self.last_command_age_s,
            sent=self.last_sent,
            feedback=feedback,
            input_vx=self.last_cmd_input_vx,
            input_vy=self.last_cmd_input_vy,
            input_wz=self.last_cmd_input_wz,
            heading_pid=self.last_heading_pid_diag,
        )
        self.data_chain_pub.publish(msg)

    def destroy_node(self) -> None:
        self.get_logger().info("Stopping wheels and closing UDP socket...")
        try:
            self.client.stop(count=12)
            self.client.close()
        except Exception as exc:
            self.get_logger().warn(f"failed to send final stop: {exc}")
        super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = UDPCmdVelBridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
