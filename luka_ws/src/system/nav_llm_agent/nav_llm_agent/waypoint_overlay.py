#!/usr/bin/env python3

from __future__ import annotations

from typing import Optional

import rclpy
from geometry_msgs.msg import PointStamped
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import Empty
from visualization_msgs.msg import Marker, MarkerArray

from nav_llm_agent.waypoint_store import default_waypoints_path, label_for, load_waypoints


TRANSIENT = QoSProfile(
    depth=1,
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    history=HistoryPolicy.KEEP_LAST,
)


class WaypointOverlay(Node):
    def __init__(self):
        super().__init__('waypoint_overlay')
        self.declare_parameter(
            'waypoints_file', default_waypoints_path())
        self._path = str(self.get_parameter('waypoints_file').value)
        self._frame_id = 'map'
        self._waypoints = {}
        self._last_click: Optional[PointStamped] = None

        self._marker_pub = self.create_publisher(
            MarkerArray, '/waypoint_markers', TRANSIENT)
        self._last_pub = self.create_publisher(
            PointStamped, '/waypoint_last_click', TRANSIENT)

        self.create_subscription(
            PointStamped, '/clicked_point', self._on_click, 10)
        self.create_subscription(
            Empty, '/waypoints_reload', self._on_reload, 10)

        self._reload()
        self.get_logger().info(
            f'waypoint_overlay ready file={self._path} '
            f'names={list(self._waypoints)}')

    def _on_click(self, msg: PointStamped) -> None:
        self._last_click = msg
        self._last_pub.publish(msg)
        self.get_logger().info(
            f'cached click ({msg.point.x:.3f}, {msg.point.y:.3f})')

    def _on_reload(self, _msg: Empty) -> None:
        self._reload()

    def _reload(self) -> None:
        self._frame_id, self._waypoints = load_waypoints(self._path)
        self._publish_markers()
        self.get_logger().info(
            f'reloaded {len(self._waypoints)} waypoints from {self._path}')

    def _publish_markers(self) -> None:
        array = MarkerArray()
        clear = Marker()
        clear.header.frame_id = self._frame_id
        clear.header.stamp = self.get_clock().now().to_msg()
        clear.ns = 'waypoints'
        clear.id = 0
        clear.action = Marker.DELETEALL
        array.markers.append(clear)

        now = self.get_clock().now().to_msg()
        for index, spec in enumerate(self._waypoints.values(), start=1):
            x = float(spec['x'])
            y = float(spec['y'])
            text = label_for(spec)

            dot = Marker()
            dot.header.frame_id = self._frame_id
            dot.header.stamp = now
            dot.ns = 'waypoints'
            dot.id = index * 2
            dot.type = Marker.SPHERE
            dot.action = Marker.ADD
            dot.pose.position.x = x
            dot.pose.position.y = y
            dot.pose.position.z = 0.08
            dot.pose.orientation.w = 1.0
            dot.scale.x = 0.18
            dot.scale.y = 0.18
            dot.scale.z = 0.18
            dot.color.r = 0.1
            dot.color.g = 0.75
            dot.color.b = 0.2
            dot.color.a = 0.95
            array.markers.append(dot)

            label = Marker()
            label.header.frame_id = self._frame_id
            label.header.stamp = now
            label.ns = 'waypoints'
            label.id = index * 2 + 1
            label.type = Marker.TEXT_VIEW_FACING
            label.action = Marker.ADD
            label.pose.position.x = x
            label.pose.position.y = y
            label.pose.position.z = 0.38
            label.pose.orientation.w = 1.0
            label.scale.z = 0.32
            # Dark green: visible on white free space (white text washed out).
            label.color.r = 0.05
            label.color.g = 0.4
            label.color.b = 0.12
            label.color.a = 1.0
            label.text = text
            array.markers.append(label)

        self._marker_pub.publish(array)


def main(args=None):
    rclpy.init(args=args)
    node = WaypointOverlay()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
