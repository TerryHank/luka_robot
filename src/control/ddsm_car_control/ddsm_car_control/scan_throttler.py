#!/usr/bin/env python3
import copy
from typing import Optional

from builtin_interfaces.msg import Time
import rclpy
from rclpy.node import Node
from rclpy.qos import (
    HistoryPolicy,
    QoSProfile,
    ReliabilityPolicy,
    qos_profile_sensor_data,
)
from sensor_msgs.msg import LaserScan


def scan_publish_qos() -> QoSProfile:
    return QoSProfile(
        history=HistoryPolicy.KEEP_LAST,
        depth=10,
        reliability=ReliabilityPolicy.RELIABLE,
    )


def should_publish_scan(
    last_publish_seconds: Optional[float],
    now_seconds: float,
    publish_period: float,
) -> bool:
    if publish_period <= 0.0:
        return True
    if last_publish_seconds is None:
        return True
    return now_seconds - last_publish_seconds >= publish_period


def prepare_scan_for_publish(msg: LaserScan, publish_stamp: Time) -> LaserScan:
    prepared = copy.deepcopy(msg)
    prepared.header.stamp = publish_stamp
    return prepared


class LaserScanThrottler(Node):
    def __init__(self) -> None:
        super().__init__("scan_throttler")
        self.declare_parameter("input_topic", "/scan_raw")
        self.declare_parameter("output_topic", "/scan")
        self.declare_parameter("publish_frequency", 3.0)

        input_topic = self.get_parameter("input_topic").value
        output_topic = self.get_parameter("output_topic").value
        publish_frequency = float(self.get_parameter("publish_frequency").value)
        self.publish_period = 1.0 / publish_frequency if publish_frequency > 0.0 else 0.0
        self.last_publish_seconds: Optional[float] = None

        self.scan_pub = self.create_publisher(
            LaserScan,
            output_topic,
            scan_publish_qos(),
        )
        self.scan_sub = self.create_subscription(
            LaserScan,
            input_topic,
            self.on_scan,
            qos_profile_sensor_data,
        )

        self.get_logger().info(
            f"Throttling LaserScan from {input_topic} to {output_topic} "
            f"at {publish_frequency:.2f} Hz"
        )

    def on_scan(self, msg: LaserScan) -> None:
        now_seconds = self.get_clock().now().nanoseconds / 1_000_000_000.0
        if not should_publish_scan(
            self.last_publish_seconds,
            now_seconds,
            self.publish_period,
        ):
            return

        self.last_publish_seconds = now_seconds
        self.scan_pub.publish(
            prepare_scan_for_publish(msg, self.get_clock().now().to_msg())
        )


def main(args=None) -> None:
    rclpy.init(args=args)
    node = LaserScanThrottler()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
