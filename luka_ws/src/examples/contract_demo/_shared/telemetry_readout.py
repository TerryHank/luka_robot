#!/usr/bin/env python3
"""Display measured feedback only; this node has no command publishers."""
import argparse
import math
import time
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from nav_msgs.msg import Odometry
from sensor_msgs.msg import Imu
from std_msgs.msg import String


def yaw(q):
    return math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))


class Readout(Node):
    def __init__(self, mode):
        super().__init__("contract_demo_" + mode + "_readout")
        self.mode = mode
        self.latest = None
        self.received = 0.
        self.previous = None
        self.distance = 0.
        self.gate = "waiting for base status"
        if mode == "odom":
            self.create_subscription(Odometry, "/wheel/odom", self.odom, qos_profile_sensor_data)
            self.create_subscription(String, "/nx/web_teleop_status",
                                     lambda m: setattr(self, "gate", m.data), 10)
        else:
            self.create_subscription(Imu, "/imu/data", self.imu, qos_profile_sensor_data)
        self.create_timer(.5, self.report)

    def fresh_stamp(self, message):
        stamp = message.header.stamp.sec + message.header.stamp.nanosec / 1e9
        age = self.get_clock().now().nanoseconds / 1e9 - stamp
        return stamp > 0 and -.1 <= age < .75

    def odom(self, message):
        if not self.fresh_stamp(message):
            return
        p = message.pose.pose.position
        if not all(math.isfinite(v) for v in (p.x, p.y)):
            return
        if self.previous is not None:
            self.distance += math.hypot(p.x - self.previous[0], p.y - self.previous[1])
        self.previous = (p.x, p.y)
        self.latest, self.received = message, time.monotonic()

    def imu(self, message):
        if self.fresh_stamp(message):
            self.latest, self.received = message, time.monotonic()

    def report(self):
        if self.latest is None or time.monotonic() - self.received > .75:
            detail = ("valid encoder-derived /wheel/odom" if self.mode == "odom"
                      else "fresh /imu/data")
            print("[WAITING] " + detail + "; no measured value is being fabricated", flush=True)
            return
        m = self.latest
        if self.mode == "odom":
            p, v = m.pose.pose.position, m.twist.twist
            print("[ODOM] x=%.4f m y=%.4f m yaw=%.2f deg | vx=%.3f vy=%.3f m/s "
                  "wz=%.3f rad/s | measured_path=%.4f m | gate=%s" %
                  (p.x, p.y, math.degrees(yaw(m.pose.pose.orientation)),
                   v.linear.x, v.linear.y, v.angular.z, self.distance, self.gate), flush=True)
        else:
            a, w = m.linear_acceleration, m.angular_velocity
            print("[IMU] ax=%+.4f ay=%+.4f az=%+.4f m/s^2 | "
                  "gx=%+.4f gy=%+.4f gz=%+.4f rad/s | frame=%s" %
                  (a.x, a.y, a.z, w.x, w.y, w.z, m.header.frame_id), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("odom", "imu"), required=True)
    args, ros_args = parser.parse_known_args()
    rclpy.init(args=ros_args)
    node = Readout(args.mode)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
