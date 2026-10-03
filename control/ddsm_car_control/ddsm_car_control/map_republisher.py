#!/usr/bin/env python3
from copy import deepcopy
from typing import Optional

import rclpy
from nav_msgs.msg import OccupancyGrid
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy


def map_qos() -> QoSProfile:
    return QoSProfile(
        history=HistoryPolicy.KEEP_LAST,
        depth=1,
        reliability=ReliabilityPolicy.RELIABLE,
        durability=DurabilityPolicy.TRANSIENT_LOCAL,
    )


def refresh_occupancy_grid_stamp(
    grid: OccupancyGrid,
    stamp,
) -> OccupancyGrid:
    refreshed = deepcopy(grid)
    refreshed.header.stamp = stamp
    return refreshed


class OccupancyGridRepublisher(Node):
    def __init__(self) -> None:
        super().__init__("map_republisher")
        self.declare_parameter("input_topic", "/slam_map")
        self.declare_parameter("output_topic", "/map")
        self.declare_parameter("publish_frequency", 2.0)
        self.declare_parameter("refresh_stamp", True)

        input_topic = self.get_parameter("input_topic").value
        output_topic = self.get_parameter("output_topic").value
        publish_frequency = float(self.get_parameter("publish_frequency").value)
        self.refresh_stamp = bool(self.get_parameter("refresh_stamp").value)
        self.latest_map: Optional[OccupancyGrid] = None

        qos = map_qos()
        self.map_sub = self.create_subscription(
            OccupancyGrid,
            input_topic,
            self.on_map,
            qos,
        )
        self.map_pub = self.create_publisher(OccupancyGrid, output_topic, qos)
        self.timer = self.create_timer(
            1.0 / max(publish_frequency, 0.1),
            self.publish_latest_map,
        )

        self.get_logger().info(
            f"Republishing maps from {input_topic} to {output_topic} "
            f"at {publish_frequency:.2f} Hz"
        )

    def on_map(self, msg: OccupancyGrid) -> None:
        self.latest_map = msg

    def publish_latest_map(self) -> None:
        if self.latest_map is None:
            return

        if self.refresh_stamp:
            msg = refresh_occupancy_grid_stamp(
                self.latest_map,
                self.get_clock().now().to_msg(),
            )
        else:
            msg = self.latest_map
        self.map_pub.publish(msg)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = OccupancyGridRepublisher()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
