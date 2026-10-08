#!/usr/bin/env python3
"""Passive, bounded Nav2 speed-chain recorder for S100 stall diagnosis.

Subscribes only.  Never publishes a goal, a velocity, or a service request.
"""

import json
import logging
from logging.handlers import RotatingFileHandler
import math
import time

import rclpy
from action_msgs.msg import GoalStatus, GoalStatusArray
from geometry_msgs.msg import Twist
from nav2_msgs.msg import CollisionMonitorState
from nav_msgs.msg import Odometry
from sensor_msgs.msg import LaserScan
from std_msgs.msg import String
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy, qos_profile_sensor_data


LOG = '/home/sunrise/luka_ws/log/nav_chain_trace.jsonl'


class Recorder(Node):
    def __init__(self):
        super().__init__('luka_nav_chain_recorder')
        self.started = time.monotonic()
        self.last = {}
        self.active_until = 0.0
        self.last_write = 0.0
        self.statuses = []
        self.log = logging.getLogger('nav_chain')
        self.log.setLevel(logging.INFO)
        handler = RotatingFileHandler(LOG, maxBytes=8_000_000, backupCount=2)
        handler.setFormatter(logging.Formatter('%(message)s'))
        self.log.addHandler(handler)

        for stage in ('raw', 'smoothed', 'guarded', 'safe'):
            self.create_subscription(
                Twist, '/nx/nav_' + stage,
                lambda msg, stage=stage: self.on_twist(stage, msg), 10)
        self.create_subscription(CollisionMonitorState, '/collision_monitor_state',
                                 self.on_collision, 10)
        self.create_subscription(String, '/lateral_escape/status', self.on_guard, 10)
        self.create_subscription(Odometry, '/wheel/odom', self.on_odom, 10)
        for name in ('scan', 'scan_low_filtered'):
            self.create_subscription(LaserScan, '/' + name,
                                     lambda msg, name=name: self.on_scan(name, msg),
                                     qos_profile_sensor_data)
        qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                         durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.create_subscription(GoalStatusArray, '/navigate_to_pose/_action/status',
                                 self.on_status, qos)
        self.create_timer(0.2, self.write_snapshot)

    def remember(self, name, value):
        self.last[name] = {'value': value, 'seen_mono': round(time.monotonic(), 3)}

    def on_twist(self, stage, msg):
        values = [round(msg.linear.x, 3), round(msg.linear.y, 3),
                  round(msg.angular.z, 3)]
        self.remember(stage, values)
        if any(abs(v) > 0.005 for v in values):
            self.active_until = time.monotonic() + 20

    def on_collision(self, msg):
        value = {'action': int(msg.action_type),
                 'polygon': str(getattr(msg, 'polygon_name', ''))}
        self.remember('collision', value)
        if value['action'] != int(CollisionMonitorState.DO_NOTHING):
            self.active_until = time.monotonic() + 20

    def on_guard(self, msg):
        self.remember('guard', str(msg.data)[:400])

    def on_odom(self, msg):
        p = msg.pose.pose.position
        v = msg.twist.twist
        self.remember('odom', [round(p.x, 3), round(p.y, 3),
                               round(v.linear.x, 3), round(v.linear.y, 3),
                               round(v.angular.z, 3)])

    def on_scan(self, name, msg):
        front = []
        for i, distance in enumerate(msg.ranges):
            angle = msg.angle_min + i * msg.angle_increment
            if abs(math.atan2(math.sin(angle), math.cos(angle))) < math.radians(35):
                if math.isfinite(distance) and msg.range_min <= distance <= msg.range_max:
                    front.append(distance)
        self.remember(name, round(min(front), 3) if front else None)

    def on_status(self, msg):
        self.statuses = [int(item.status) for item in msg.status_list]
        if any(value in (GoalStatus.STATUS_ACCEPTED, GoalStatus.STATUS_EXECUTING,
                         GoalStatus.STATUS_CANCELING) for value in self.statuses):
            self.active_until = time.monotonic() + 20

    def write_snapshot(self):
        now = time.monotonic()
        active = now < self.active_until
        if not active and now - self.last_write < 5:
            return
        self.last_write = now
        row = {'wall_time': round(time.time(), 3), 'active': active,
               'nav_statuses': self.statuses,
               'topics': {name: {'value': data['value'],
                                 'age_s': round(now - data['seen_mono'], 2)}
                          for name, data in self.last.items()}}
        self.log.info(json.dumps(row, ensure_ascii=False, separators=(',', ':')))


def main():
    rclpy.init()
    node = Recorder()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
