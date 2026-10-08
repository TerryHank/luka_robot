#!/usr/bin/env python3

import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import PointCloud2, PointField


class ColoredPointCloudRelay(Node):
    def __init__(self):
        super().__init__("colored_point_cloud_relay")
        self.publisher = self.create_publisher(
            PointCloud2, "/camera/colored_points", qos_profile_sensor_data
        )
        self.subscription = None
        self.create_timer(0.5, self._update_subscription)

    def _update_subscription(self) -> None:
        needed = self.publisher.get_subscription_count() > 0
        if needed and self.subscription is None:
            self.subscription = self.create_subscription(
                PointCloud2,
                "/camera/depth_registered/points",
                self._relay,
                qos_profile_sensor_data,
            )
        elif not needed and self.subscription is not None:
            self.destroy_subscription(self.subscription)
            self.subscription = None

    def _relay(self, message: PointCloud2) -> None:
        for field in message.fields:
            if field.name == "rgb" and field.datatype == PointField.FLOAT32:
                field.datatype = PointField.UINT32
        self.publisher.publish(message)


def main(args=None):
    rclpy.init(args=args)
    node = ColoredPointCloudRelay()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
