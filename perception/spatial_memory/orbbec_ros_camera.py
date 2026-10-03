"""Consume registered Orbbec RGB-D topics without opening the USB device."""
import os
import threading
import time
from collections import deque

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
        self.depth_reason = 'waiting_for_rgbd'
        self.rgbd_dt_ms = None
        self.rgb_stamp = None
        self.depth_stamp = None
        self.calibration = {'source': 'orbbec_ros_factory', 'color': [0.] * 4,
                            'color_dist': [0.] * 5, 'metric_depth_available': False}
        self.people_calibration = self.calibration
        self.rgb = self.depth = self.info = None
        self.color_buffer = deque(maxlen=max(3, int(os.getenv('NX_RGBD_BUFFER_SIZE', '10'))))
        self.depth_buffer = deque(maxlen=max(3, int(os.getenv('NX_RGBD_BUFFER_SIZE', '10'))))
        self.max_rgbd_dt = float(os.getenv('NX_RGBD_SYNC_TOLERANCE', '0.12'))
        self.last_used_color_stamp = None
        self.last_used_depth_stamp = None
        self.last_match_mono = None
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
            stamp = self._stamp(msg)
            rgb = self.bridge.imgmsg_to_cv2(msg, 'bgr8')
            self.rgb = (msg, rgb)
            self.color_buffer.append((stamp, msg, rgb))
            self._try_match_rgbd()
        except Exception as exc:
            self.error = str(exc)
            self.depth_reason = 'rgb_decode_error'
            self.has_metric_depth = False
            self.calibration['metric_depth_available'] = False

    def _depth(self, msg):
        try:
            if msg.encoding not in ('16UC1', 'mono16'):
                raise ValueError('Expected Orbbec depth in uint16 millimetres')
            stamp = self._stamp(msg)
            depth = self.bridge.imgmsg_to_cv2(msg, 'passthrough')
            self.depth = (msg, depth)
            self.depth_buffer.append((stamp, msg, depth))
            self._try_match_rgbd()
        except Exception as exc:
            self.error = str(exc)
            self.depth_reason = 'depth_decode_error'
            self.has_metric_depth = False
            self.calibration['metric_depth_available'] = False

    def _info(self, msg):
        self.info = msg
        self._try_match_rgbd()

    def _try_match_rgbd(self):
        if self.info is None or not self.color_buffer or not self.depth_buffer:
            return
        chosen = None
        for color_stamp, color_msg, rgb in reversed(self.color_buffer):
            if color_stamp == self.last_used_color_stamp:
                continue
            depth_stamp, depth_msg, depth = min(
                self.depth_buffer, key=lambda item: abs(color_stamp - item[0]))
            if depth_stamp == self.last_used_depth_stamp:
                continue
            dt = abs(color_stamp - depth_stamp)
            if dt <= self.max_rgbd_dt:
                chosen = (color_stamp, color_msg, rgb, depth_stamp, depth_msg, depth, dt)
                break
        if chosen is None:
            if (self.last_match_mono is None or
                    time.monotonic() - self.last_match_mono > .9):
                self.has_metric_depth = False
                self.calibration['metric_depth_available'] = False
                self.depth_reason = 'rgbd_sync_timeout'
                self.error = 'RGB-D timestamp matching exceeded %.0f ms' % (self.max_rgbd_dt * 1000)
            return
        color_stamp, color_msg, rgb, depth_stamp, depth_msg, depth, dt = chosen
        info = self.info
        if (rgb.shape[:2] != (480, 640) or depth.shape != (480, 640)
                or depth.dtype != np.uint16
                or color_msg.header.frame_id != depth_msg.header.frame_id
                or info.header.frame_id != color_msg.header.frame_id
                or (info.width, info.height) != (640, 480)
                or min(info.k[0], info.k[4]) < 100):
            self.has_metric_depth = False
            self.calibration['metric_depth_available'] = False
            self.depth_reason = 'rgbd_format_invalid'
            self.error = 'Orbbec RGB-D frames are not registered or have invalid format'
            return
        stamp = min(color_stamp, depth_stamp)
        age = time.time() - stamp
        if not 0 <= age <= .9:
            self.has_metric_depth = False
            self.calibration['metric_depth_available'] = False
            self.depth_reason = 'rgbd_stale'
            self.error = 'Orbbec RGB-D frame timestamp is stale'
            return
        mono = time.monotonic() - age
        with self.latest_lock:
            self.calibration['color'] = [info.k[0], info.k[4], info.k[2], info.k[5]]
            self.calibration['color_dist'] = list(info.d)
            self.calibration['metric_depth_available'] = True
            self.has_metric_depth = True
            self.depth_reason = 'rgbd_sync_valid'
            self.rgbd_dt_ms = dt * 1000.0
            self.rgb_stamp = color_stamp
            self.depth_stamp = depth_stamp
            self.latest = (stamp, mono, rgb, depth, dt)
            self.latest_high = (mono, rgb)
            self.last_match_mono = time.monotonic()
            self.error = None
        self.last_used_color_stamp = color_stamp
        self.last_used_depth_stamp = depth_stamp
        self.color_buffer = deque(
            (item for item in self.color_buffer if item[0] > color_stamp),
            maxlen=self.color_buffer.maxlen)
        self.depth_buffer = deque(
            (item for item in self.depth_buffer if item[0] > depth_stamp),
            maxlen=self.depth_buffer.maxlen)

    def people_snapshot(self):
        with self.latest_lock:
            return self.latest, self.latest_high

    def close(self):
        self.executor.shutdown(timeout_sec=2)
        self.thread.join(timeout=2)
        self.node.destroy_node()
        self.context.shutdown()