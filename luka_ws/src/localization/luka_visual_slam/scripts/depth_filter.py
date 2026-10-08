#!/usr/bin/env python3
"""Project an already aligned dynamic mask into registered depth; no inference."""
import json
import time
import message_filters
import rclpy
from rclpy.node import Node
from rclpy.executors import ExternalShutdownException
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image, CameraInfo
from std_msgs.msg import String
from cv_bridge import CvBridge
from luka_visual_slam.contracts import masked_depth, validate_pair


class DepthFilter(Node):
    def __init__(self):
        super().__init__('dynamic_depth_filter')
        self.bridge = CvBridge()
        self.last = 0
        self.state = 'waiting_for_rgbd_and_mask'
        self.rgb_out = self.create_publisher(Image, 'filtered/rgb', 5)
        self.depth_out = self.create_publisher(Image, 'filtered/depth', 5)
        self.info_out = self.create_publisher(CameraInfo, 'filtered/camera_info', 5)
        self.status = self.create_publisher(String, 'depth_filter/status', 5)
        self.inputs = [message_filters.Subscriber(self, kind, topic, qos_profile=qos_profile_sensor_data)
                       for kind, topic in ((Image,'rgb'),(Image,'depth'),(CameraInfo,'camera_info'),(Image,'dynamic_mask'))]
        self.sync = message_filters.ApproximateTimeSynchronizer(self.inputs, 20, .06)
        self.sync.registerCallback(self.pair)
        self.create_timer(1., self.report)

    def report(self):
        state = self.state if time.monotonic()-self.last < 1.0 else 'waiting_for_fresh_rgbd_and_mask'
        self.status.publish(String(data=json.dumps({'state': state, 'raw_fallback': False})))

    def pair(self, rgb, depth, info, mask):
        try:
            messages = (rgb,depth,info,mask)
            stamps = [m.header.stamp.sec+m.header.stamp.nanosec*1e-9 for m in messages]
            validate_pair(stamps, [m.header.frame_id for m in messages], self.get_clock().now().nanoseconds/1e9)
            if mask.encoding != 'mono8' or depth.encoding not in ('16UC1','32FC1'):
                raise ValueError('unsupported mask/depth encoding')
            if len({(m.width,m.height) for m in messages}) != 1:
                raise ValueError('unaligned input sizes')
            array = masked_depth(self.bridge.imgmsg_to_cv2(depth),self.bridge.imgmsg_to_cv2(mask))
            output = self.bridge.cv2_to_imgmsg(array,encoding=depth.encoding)
            output.header = depth.header
            self.rgb_out.publish(rgb); self.info_out.publish(info); self.depth_out.publish(output)
            self.state = 'filtered'; self.last = time.monotonic()
        except (ValueError,TypeError) as error:
            self.state = str(error); self.last = time.monotonic(); self.report()


def main():
    rclpy.init(); node=DepthFilter()
    try: rclpy.spin(node)
    except (KeyboardInterrupt,ExternalShutdownException): pass
    finally:
        node.destroy_node()
        if rclpy.ok(): rclpy.shutdown()


if __name__ == '__main__': main()
