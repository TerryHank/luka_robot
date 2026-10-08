#!/usr/bin/env python3
"""Read-only fresh graph evidence. Exits nonzero for absent required live interfaces."""
import json
import time

import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from nav2_msgs.action import NavigateToPose, Spin
from tf2_ros import Buffer, TransformListener
from rclpy.time import Time


def main():
    rclpy.init()
    node = Node('person_follow_preflight')
    buffer = Buffer()
    listener = TransformListener(buffer, node)
    client = ActionClient(node, NavigateToPose, '/navigate_to_pose')
    spin_client = ActionClient(node, Spin, '/spin')
    end = time.monotonic() + 3.0
    while time.monotonic() < end:
        rclpy.spin_once(node, timeout_sec=0.1)
    expected = {'/camera/color/image_raw': 'sensor_msgs/msg/Image',
                '/camera/depth/image_raw': 'sensor_msgs/msg/Image',
                '/camera/color/camera_info': 'sensor_msgs/msg/CameraInfo',
                '/hobot_dnn_seg': 'ai_msgs/msg/PerceptionTargets',
                '/tros_fusion_interaction': 'ai_msgs/msg/PerceptionTargets',
                '/tros_mot_targets': 'ai_msgs/msg/PerceptionTargets',
                '/global_costmap/costmap': 'nav_msgs/msg/OccupancyGrid',
                '/wheel/odom': 'nav_msgs/msg/Odometry'}
    evidence = {'nodes': node.get_node_names_and_namespaces(), 'topics': {}, 'tf': {},
                'action_ready': client.server_is_ready(),
                'spin_action_ready': spin_client.server_is_ready()}
    ok = evidence['action_ready'] and evidence['spin_action_ready']
    for topic, msg_type in expected.items():
        endpoints = node.get_publishers_info_by_topic(topic)
        evidence['topics'][topic] = [{'node': e.node_name, 'namespace': e.node_namespace,
                                     'type': e.topic_type, 'qos': str(e.qos_profile)} for e in endpoints]
        ok = ok and len(endpoints) == 1 and endpoints[0].topic_type == msg_type
    for parent, child in [('map', 'base_link'), ('map', 'camera_link')]:
        try:
            transform = buffer.lookup_transform(parent, child, Time())
            evidence['tf'][parent + '<-' + child] = str(transform)
        except Exception as error:
            evidence['tf'][parent + '<-' + child] = str(error)
            ok = False
    print(json.dumps(evidence, indent=2, ensure_ascii=False))
    node.destroy_node()
    rclpy.shutdown()
    raise SystemExit(0 if ok else 2)


if __name__ == '__main__':
    main()
