#!/usr/bin/env python3
"""Bounded approximate RGB-D pairing for the official fusion's ExactTime input."""
import copy
import math
import message_filters
import rclpy
from rclpy.node import Node
from rclpy.executors import ExternalShutdownException
from ai_msgs.msg import PerceptionTargets
from sensor_msgs.msg import Image
from std_msgs.msg import Float64


def stamp_seconds(stamp):
    return stamp.sec + stamp.nanosec * 1e-9


class Pairer(Node):
    def __init__(self):
        super().__init__('person_follow_depth_pair')
        self.declare_parameter('depth_topic', '/camera/depth/image_raw')
        self.declare_parameter('seg_topic', '/hobot_dnn_seg')
        self.declare_parameter('max_skew_sec', 0.04)
        self.limit = self.get_parameter('max_skew_sec').value
        if self.limit <= 0 or self.limit > 0.05:
            raise ValueError('Depth pairing skew must be within (0, 0.05] seconds')
        self.depth_out = self.create_publisher(Image, '/person_follow/fusion/depth', 10)
        self.seg_out = self.create_publisher(PerceptionTargets, '/person_follow/fusion/seg', 10)
        self.skew_out = self.create_publisher(Float64, '/person_follow/pair_skew_sec', 10)
        self.depth_sub = message_filters.Subscriber(self, Image, self.get_parameter('depth_topic').value)
        self.seg_sub = message_filters.Subscriber(self, PerceptionTargets, self.get_parameter('seg_topic').value)
        self.sync = message_filters.ApproximateTimeSynchronizer(
            [self.depth_sub, self.seg_sub], 30, self.limit)
        self.sync.registerCallback(self.pair)

    def pair(self, depth, seg):
        skew = stamp_seconds(depth.header.stamp) - stamp_seconds(seg.header.stamp)
        age = self.get_clock().now().nanoseconds * 1e-9 - stamp_seconds(seg.header.stamp)
        if abs(skew) > self.limit or age < -0.05 or age > 0.6:
            return
        if (depth.encoding != '16UC1' or depth.is_bigendian or depth.step != depth.width * 2 or
                len(depth.data) != depth.step * depth.height or depth.header.frame_id != seg.header.frame_id):
            self.get_logger().error('Invalid registered-depth encoding, dimensions or frame; pair dropped')
            return
        masks = [c for target in seg.targets for c in target.captures]
        if not masks or any(c.img.width == 0 or c.img.height == 0 or
                            len(c.features) != c.img.width * c.img.height or
                            any(not math.isfinite(v) for v in c.features) for c in masks):
            self.get_logger().error('Missing or invalid real segmentation mask; pair dropped')
            return
        paired = Image()
        paired.header = copy.deepcopy(depth.header)
        # Registered image geometry is unchanged; preserve original timing difference separately.
        paired.header.stamp = seg.header.stamp
        paired.width, paired.height, paired.encoding, paired.step = depth.width, depth.height, depth.encoding, depth.step
        paired.data = depth.data
        self.skew_out.publish(Float64(data=skew))
        self.depth_out.publish(paired)
        self.seg_out.publish(seg)


def main():
    rclpy.init()
    node = Pairer()
    try: rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException): pass
    finally:
        node.destroy_node()
        if rclpy.ok(): rclpy.shutdown()


if __name__ == '__main__':
    main()
