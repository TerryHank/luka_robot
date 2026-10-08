#!/usr/bin/env python3
"""Format conversion only; retain resolution, header and calibrated image geometry."""
import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.executors import ExternalShutdownException
from rclpy.qos import qos_profile_sensor_data
from cv_bridge import CvBridge
from sensor_msgs.msg import Image


def convert(rgb):
    height, width = rgb.shape[:2]
    if height % 2 or width % 2:
        raise ValueError('NV12 requires even image dimensions')
    i420 = cv2.cvtColor(rgb, cv2.COLOR_RGB2YUV_I420).reshape(-1)
    y_size, chroma_size = width * height, width * height // 4
    uv = np.empty(chroma_size * 2, dtype=np.uint8)
    uv[0::2] = i420[y_size:y_size + chroma_size]
    uv[1::2] = i420[y_size + chroma_size:]
    return np.concatenate((i420[:y_size], uv)).tobytes()


class Converter(Node):
    def __init__(self):
        super().__init__('person_follow_image_format')
        self.declare_parameter('input_topic', '/camera/color/image_raw')
        self.declare_parameter('output_topic', '/person_follow/image_nv12')
        self.bridge = CvBridge()
        self.publisher = self.create_publisher(Image, self.get_parameter('output_topic').value, 2)
        self.create_subscription(Image, self.get_parameter('input_topic').value,
                                 self.callback, qos_profile_sensor_data)

    def callback(self, msg):
        if msg.encoding not in ('rgb8', 'bgr8') or msg.height % 2 or msg.width % 2:
            self.get_logger().error('Unsupported image format/dimensions; no image forwarded')
            return
        rgb = self.bridge.imgmsg_to_cv2(msg, desired_encoding='rgb8')
        output = Image()
        output.header = msg.header
        output.width, output.height, output.step = msg.width, msg.height, msg.width
        output.encoding = 'nv12'
        output.data = convert(rgb)
        self.publisher.publish(output)


def main():
    rclpy.init()
    node = Converter()
    try: rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException): pass
    finally:
        node.destroy_node()
        if rclpy.ok(): rclpy.shutdown()


if __name__ == '__main__':
    main()
