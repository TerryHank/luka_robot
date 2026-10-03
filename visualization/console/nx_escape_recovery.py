"""Bounded lidar-checked recovery through the existing base teleop safety path.

Disabled unless NX_SAFE_ESCAPE=1. The dashboard may only call ``run`` after a
Nav2 goal has stopped and the navigation gate has been closed. The base's own
encoder/scan watchdog and directional obstacle checks remain in series.
"""

import math
import os
import threading
import time

from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import LaserScan

from nx_safe_escape import check_translation, choose_escape
from web_teleop_safety import SENSORS, nearby_points


def yaw_of(q):
    return math.atan2(2 * (q.w*q.z+q.x*q.y), 1-2*(q.y*q.y+q.z*q.z))


class EscapeRecovery:
    def __init__(self, node):
        self.node = node
        self.enabled = os.getenv('NX_SAFE_ESCAPE', '0') == '1'
        self.lock = threading.RLock()
        self.cancelled = threading.Event()
        self.running = False
        self.scans = {}
        self.odom = None
        self.last_result = {'ok': False, 'reason': '尚未执行'}
        self.pub = node.create_publisher(Twist, '/nx/web_teleop_cmd_vel', 10)
        self.subscriptions = [node.create_subscription(
            LaserScan, topic, lambda msg, key=topic: self._scan(key, msg),
            qos_profile_sensor_data) for topic in SENSORS]
        self.subscriptions.append(node.create_subscription(
            Odometry, '/wheel/odom', self._odom, qos_profile_sensor_data))

    def _scan(self, topic, msg):
        with self.lock:
            self.scans[topic] = (msg, time.monotonic())

    def _odom(self, msg):
        with self.lock:
            self.odom = (msg, time.monotonic())

    def _snapshot(self):
        with self.lock:
            now = time.monotonic()
            if any(topic not in self.scans or now-self.scans[topic][1] > .35
                   for topic in SENSORS):
                return None, None, '高低雷达数据不齐或过期'
            if self.odom is None or now-self.odom[1] > .35:
                return None, None, '编码器里程计过期'
            ros_now = self.node.get_clock().now().nanoseconds
            for topic in SENSORS:
                scan = self.scans[topic][0]
                if abs(scan.angle_increment)*(len(scan.ranges)-1) < 5.5:
                    return None, None, topic+' 的雷达视野不足'
                stamp = scan.header.stamp
                age = (ros_now - stamp.sec*10**9 - stamp.nanosec)/1e9
                if not -.1 < age < .5:
                    return None, None, topic+' 的采样时间过期'
            points = []
            for topic, sensor_pose in SENSORS.items():
                points.extend(nearby_points(self.scans[topic][0], sensor_pose))
            return points, self.odom[0], None

    def preview(self):
        points, _, error = self._snapshot()
        return {'safe': False, 'reason': error} if error else choose_escape(points)

    def cancel(self, reason='已取消脱困'):
        self.cancelled.set()
        self.pub.publish(Twist())
        with self.lock:
            if self.running:
                self.last_result = {'ok': False, 'reason': reason}

    def _publish(self, direction):
        if self.cancelled.is_set():
            return
        msg = Twist()
        if direction == 'back': msg.linear.x = -.06
        elif direction == 'left': msg.linear.y = .05
        elif direction == 'right': msg.linear.y = -.05
        self.pub.publish(msg)

    def run(self, teleop_active, required_direction=None):
        result = self._run_once(teleop_active, required_direction)
        with self.lock:
            self.last_result = result
        return result

    def _run_once(self, teleop_active, required_direction=None):
        """Execute at most 5 cm, 2 s, one translation; never rotates."""
        if not self.enabled:
            return {'ok': False, 'reason': '自动脱困尚未启用'}
        with self.lock:
            if self.running:
                return {'ok': False, 'reason': '已有脱困动作'}
            self.running = True
            self.cancelled.clear()
        try:
            if teleop_active():
                return {'ok': False, 'reason': '网页遥控正在使用'}
            points, start_odom, error = self._snapshot()
            if error:
                return {'ok': False, 'reason': error}
            choice = choose_escape(points)
            if not choice['safe']:
                return {'ok': False, 'reason': choice['reason']}
            direction = choice['direction']
            if required_direction and direction != required_direction:
                return {'ok': False, 'reason': '实际安全方向已变化，未执行动作'}
            target = choice['distance_m']
            start = start_odom.pose.pose
            x0, y0, yaw0 = start.position.x, start.position.y, yaw_of(start.orientation)
            began = time.monotonic()
            last_progress_at = began
            best_progress = 0.0
            while time.monotonic()-began < 2.0:
                if self.cancelled.is_set() or teleop_active():
                    return {'ok': False, 'reason': '脱困被遥控或停车接管'}
                points, odom, error = self._snapshot()
                if error:
                    return {'ok': False, 'reason': error}
                current = odom.pose.pose
                ux = math.cos(yaw0)*(current.position.x-x0)+math.sin(yaw0)*(current.position.y-y0)
                uy = -math.sin(yaw0)*(current.position.x-x0)+math.cos(yaw0)*(current.position.y-y0)
                progress = -ux if direction == 'back' else uy if direction == 'left' else -uy
                drift = abs(uy) if direction == 'back' else abs(ux)
                angle_error = abs(math.atan2(math.sin(yaw_of(current.orientation)-yaw0),
                                             math.cos(yaw_of(current.orientation)-yaw0)))
                if progress >= target:
                    return {'ok': True, 'reason': '已完成短距离脱困',
                            'direction': direction, 'moved_m': round(progress, 3)}
                if progress < -.015 or drift > .025 or angle_error > .12:
                    return {'ok': False, 'reason': '移动方向或姿态异常，已停车'}
                if progress > best_progress+.003:
                    best_progress, last_progress_at = progress, time.monotonic()
                if time.monotonic()-last_progress_at > .7:
                    return {'ok': False, 'reason': '底盘未移动，已停止脱困'}
                remaining = min(target-progress, .06)
                dx = -remaining if direction == 'back' else 0.
                dy = remaining if direction == 'left' else -remaining if direction == 'right' else 0.
                check = check_translation(points, dx, dy)
                if not check['safe']:
                    return {'ok': False, 'reason': check['reason']}
                self._publish(direction)
                time.sleep(.08)
            return {'ok': False, 'reason': '脱困动作超时'}
        finally:
            for _ in range(3):
                self.pub.publish(Twist())
                time.sleep(.04)
            with self.lock:
                self.running = False
