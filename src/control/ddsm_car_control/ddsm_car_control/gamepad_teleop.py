#!/usr/bin/env python3

import math
import time

import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Joy
from std_msgs.msg import Bool


def shaped_axis(value: float, deadzone: float, exponent: float) -> float:
    """Apply a rescaled deadzone and response curve while preserving the sign."""
    value = max(-1.0, min(1.0, float(value)))
    magnitude = abs(value)
    if magnitude <= deadzone:
        return 0.0
    normalized = (magnitude - deadzone) / max(1.0 - deadzone, 1.0e-6)
    return math.copysign(normalized**exponent, value)


class GamepadTeleop(Node):
    def __init__(self) -> None:
        super().__init__("gamepad_teleop")

        self.declare_parameter("joy_topic", "/joy")
        self.declare_parameter("cmd_vel_topic", "/cmd_vel")
        self.declare_parameter("enabled_topic", "/gamepad/enabled")

        self.declare_parameter("axis_forward", 1)
        self.declare_parameter("axis_lateral", 0)
        self.declare_parameter("axis_yaw", 3)
        self.declare_parameter("enable_button", 4)
        self.declare_parameter("turbo_button", 5)
        self.declare_parameter("require_enable_button", True)
        self.declare_parameter("speed_down_button", 2)
        self.declare_parameter("speed_up_button", 3)

        self.declare_parameter("scale_forward", 0.30)
        self.declare_parameter("scale_lateral", 0.20)
        self.declare_parameter("scale_yaw", 0.80)
        self.declare_parameter("turbo_scale_forward", 0.45)
        self.declare_parameter("turbo_scale_lateral", 0.30)
        self.declare_parameter("turbo_scale_yaw", 1.20)

        self.declare_parameter("deadzone", 0.10)
        self.declare_parameter("axis_exponent", 1.50)
        self.declare_parameter("publish_rate", 30.0)
        self.declare_parameter("joy_timeout", 0.35)
        self.declare_parameter("stop_publish_duration", 0.30)

        self.joy_topic = str(self.get_parameter("joy_topic").value)
        self.cmd_vel_topic = str(self.get_parameter("cmd_vel_topic").value)
        self.enabled_topic = str(self.get_parameter("enabled_topic").value)

        self.axis_forward = int(self.get_parameter("axis_forward").value)
        self.axis_lateral = int(self.get_parameter("axis_lateral").value)
        self.axis_yaw = int(self.get_parameter("axis_yaw").value)
        self.enable_button = int(self.get_parameter("enable_button").value)
        self.turbo_button = int(self.get_parameter("turbo_button").value)
        self.require_enable_button = bool(
            self.get_parameter("require_enable_button").value
        )
        self.speed_down_button=int(self.get_parameter("speed_down_button").value)
        self.speed_up_button=int(self.get_parameter("speed_up_button").value)
        self.speed_gear=1
        self.previous_speed_buttons=None

        self.scale_forward = float(self.get_parameter("scale_forward").value)
        self.scale_lateral = float(self.get_parameter("scale_lateral").value)
        self.scale_yaw = float(self.get_parameter("scale_yaw").value)
        self.turbo_scale_forward = float(
            self.get_parameter("turbo_scale_forward").value
        )
        self.turbo_scale_lateral = float(
            self.get_parameter("turbo_scale_lateral").value
        )
        self.turbo_scale_yaw = float(
            self.get_parameter("turbo_scale_yaw").value
        )

        self.deadzone = min(
            0.95, max(0.0, float(self.get_parameter("deadzone").value))
        )
        self.axis_exponent = max(
            0.1, float(self.get_parameter("axis_exponent").value)
        )
        publish_rate = max(1.0, float(self.get_parameter("publish_rate").value))
        self.joy_timeout = max(
            0.05, float(self.get_parameter("joy_timeout").value)
        )
        self.stop_publish_duration = max(
            0.0, float(self.get_parameter("stop_publish_duration").value)
        )

        self.cmd_pub = self.create_publisher(Twist, self.cmd_vel_topic, 10)
        self.enabled_pub = self.create_publisher(Bool, self.enabled_topic, 10)
        self.joy_sub = self.create_subscription(
            Joy, self.joy_topic, self._joy_callback, qos_profile_sensor_data
        )
        self.timer = self.create_timer(1.0 / publish_rate, self._timer_callback)

        self.last_joy: Joy | None = None
        self.last_joy_monotonic = 0.0
        self.was_active = False
        self.stop_until = 0.0
        self.last_enabled_state: bool | None = None

        self.get_logger().info(
            "Gamepad ready: hold button "
            f"{self.enable_button} to drive; axes forward/lateral/yaw="
            f"{self.axis_forward}/{self.axis_lateral}/{self.axis_yaw}; "
            f"publishing to {self.cmd_vel_topic}"
        )

    def _joy_callback(self, msg: Joy) -> None:
        now=time.monotonic()
        buttons=(self._button(msg,self.speed_down_button),self._button(msg,self.speed_up_button))
        previous=self.previous_speed_buttons
        # Ignore held buttons at startup/reconnect. One rising edge = one step.
        if previous is not None and now-self.last_joy_monotonic <= self.joy_timeout:
            if not self._button(msg,self.enable_button) and buttons[0] != buttons[1]:
                delta=-1 if buttons[0] and not previous[0] else (1 if buttons[1] and not previous[1] else 0)
                gear=max(1,min(5,self.speed_gear+delta))
                if gear!=self.speed_gear:
                    self.speed_gear=gear
                    self.get_logger().info(f'手柄速度 {gear}/5：前进最高 {self.scale_forward*(1+(gear-1)*.25):.2f} 米/秒')
        self.previous_speed_buttons=buttons
        self.last_joy = msg
        self.last_joy_monotonic = now

    @staticmethod
    def _button(msg: Joy, index: int) -> bool:
        return 0 <= index < len(msg.buttons) and bool(msg.buttons[index])

    def _axis(self, msg: Joy, index: int) -> float:
        if 0 <= index < len(msg.axes):
            return shaped_axis(msg.axes[index], self.deadzone, self.axis_exponent)
        self.get_logger().warn(
            f"Joy has {len(msg.axes)} axes, but axis {index} was requested",
            throttle_duration_sec=5.0,
        )
        return 0.0

    def _is_active(self, now: float) -> bool:
        if self.last_joy is None:
            return False
        if now - self.last_joy_monotonic > self.joy_timeout:
            return False
        if not self.require_enable_button:
            return True
        return self._button(self.last_joy, self.enable_button)

    def _publish_enabled(self, enabled: bool) -> None:
        if self.last_enabled_state == enabled:
            return
        self.enabled_pub.publish(Bool(data=enabled))
        self.last_enabled_state = enabled
        self.get_logger().info("Gamepad control enabled" if enabled else "Gamepad control stopped")

    def _timer_callback(self) -> None:
        now = time.monotonic()
        active = self._is_active(now)
        self._publish_enabled(active)

        if active and self.last_joy is not None:
            turbo = self._button(self.last_joy, self.turbo_button)
            forward_scale = (
                self.turbo_scale_forward if turbo else self.scale_forward
            )
            lateral_scale = (
                self.turbo_scale_lateral if turbo else self.scale_lateral
            )
            yaw_scale = self.turbo_scale_yaw if turbo else self.scale_yaw
            forward_scale *= (1+(self.speed_gear-1)*.25)
            lateral_scale *= (1+(self.speed_gear-1)*.25)
            yaw_scale *= (1+(self.speed_gear-1)*.25)

            cmd = Twist()
            cmd.linear.x = forward_scale * self._axis(
                self.last_joy, self.axis_forward
            )
            cmd.linear.y = lateral_scale * self._axis(
                self.last_joy, self.axis_lateral
            )
            cmd.angular.z = yaw_scale * self._axis(self.last_joy, self.axis_yaw)
            self.cmd_pub.publish(cmd)
        elif self.was_active:
            self.stop_until = now + self.stop_publish_duration
            self.cmd_pub.publish(Twist())
        elif now < self.stop_until:
            self.cmd_pub.publish(Twist())

        self.was_active = active

    def stop(self) -> None:
        # SIGINT may already have invalidated the rclpy context before the
        # executor returns. In that case the drivetrain command watchdog is
        # the safe stop path and publishing would only raise RCLError.
        if not rclpy.ok():
            return
        for _ in range(3):
            self.cmd_pub.publish(Twist())


def main(args=None) -> None:
    rclpy.init(args=args)
    node = GamepadTeleop()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.stop()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
