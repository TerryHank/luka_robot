"""Consume registered Orbbec RGB-D topics without opening the USB device."""
import threading
import time

import numpy as np
import rclpy
from cv_bridge import CvBridge
from rclpy.context import Context
from rclpy.executors import SingleThreadedExecutor
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CameraInfo, Image


class OrbbecRosCamera:
    def __init__(self):
        self.latest = self.latest_high = None
        self.latest_lock = threading.Lock()
        self.has_metric_depth = False
        self.full_fov_people = False
        self.error = 'Waiting for registered Orbbec RGB-D topics'
        self.calibration = {'source': 'orbbec_ros_factory', 'color': [0.] * 4,
                            'color_dist': [0.] * 5, 'metric_depth_available': False}
        self.people_calibration = self.calibration
        self.rgb = self.depth = self.info = None
        self.bridge = CvBridge()
        self.context = Context()
        rclpy.init(args=[], context=self.context)
        self.node = rclpy.create_node('nx_orbbec_frame_bridge', context=self.context)
        self.executor = SingleThreadedExecutor(context=self.context)
        self.executor.add_node(self.node)
        self.subscriptions = [
            self.node.create_subscription(Image, '/camera/color/image_raw', self._color, qos_profile_sensor_data),
            self.node.create_subscription(Image, '/camera/depth/image_raw', self._depth, qos_profile_sensor_data),
            self.node.create_subscription(CameraInfo, '/camera/color/camera_info', self._info, qos_profile_sensor_data),
        ]
        self.thread = threading.Thread(target=self.executor.spin, daemon=True)
        self.thread.start()

    @staticmethod
    def _stamp(msg):
        return msg.header.stamp.sec + msg.header.stamp.nanosec / 1e9

    def _color(self, msg):
        try:
            self.rgb = (msg, self.bridge.imgmsg_to_cv2(msg, 'bgr8'))
            self._publish()
        except Exception as exc:
            self.error = str(exc)
            self.has_metric_depth = False

    def _depth(self, msg):
        try:
            if msg.encoding not in ('16UC1', 'mono16'):
                raise ValueError('Expected Orbbec depth in uint16 millimetres')
            self.depth = (msg, self.bridge.imgmsg_to_cv2(msg, 'passthrough'))
            self._publish()
        except Exception as exc:
            self.error = str(exc)
            self.has_metric_depth = False

    def _info(self, msg):
        self.info = msg
        self._publish()

    def _publish(self):
        if self.rgb is None or self.depth is None or self.info is None:
            return
        color_msg, rgb = self.rgb
        depth_msg, depth = self.depth
        info = self.info
        skew = abs(self._stamp(color_msg) - self._stamp(depth_msg))
        if (rgb.shape[:2] != (480, 640) or depth.shape != (480, 640)
                or depth.dtype != np.uint16 or skew > .05
                or color_msg.header.frame_id != depth_msg.header.frame_id
                or info.header.frame_id != color_msg.header.frame_id
                or (info.width, info.height) != (640, 480)
                or min(info.k[0], info.k[4]) < 100):
            self.error = 'Orbbec RGB-D frames are not registered or synchronized'
            self.has_metric_depth = False
            return
        stamp = min(self._stamp(color_msg), self._stamp(depth_msg))
        age = time.time() - stamp
        if not 0 <= age <= .9:
            self.error = 'Orbbec RGB-D frame timestamp is stale'
            self.has_metric_depth = False
            return
        mono = time.monotonic() - age
        with self.latest_lock:
            self.calibration['color'] = [info.k[0], info.k[4], info.k[2], info.k[5]]
            self.calibration['color_dist'] = list(info.d)
            self.calibration['metric_depth_available'] = True
            self.has_metric_depth = True
            self.latest = (stamp, mono, rgb, depth, skew)
            self.latest_high = (mono, rgb)
            self.error = None

    def people_snapshot(self):
        with self.latest_lock:
            return self.latest, self.latest_high

    def close(self):
        self.executor.shutdown(timeout_sec=2)
        self.thread.join(timeout=2)
        self.node.destroy_node()
        self.context.shutdown()
