"""Read-only proximity probe for S100 web teleop commissioning."""
import time

import rclpy
from sensor_msgs.msg import LaserScan
from rclpy.qos import qos_profile_sensor_data

from web_teleop_safety import SENSORS, nearby_points, blocked


def main():
    rclpy.init()
    node = rclpy.create_node('web_teleop_probe')
    scans = {}
    for topic in SENSORS:
        node.create_subscription(LaserScan, topic,
                                 lambda msg, name=topic: scans.__setitem__(name, nearby_points(msg, SENSORS[name])),
                                 qos_profile_sensor_data)
    deadline = time.monotonic() + 5.0
    while len(scans) < len(SENSORS) and time.monotonic() < deadline:
        rclpy.spin_once(node, timeout_sec=.2)
    points = [point for topic in SENSORS for point in scans.get(topic, ())]
    print({'received': {topic: len(scans.get(topic, ())) for topic in SENSORS},
           'blocked': {direction: blocked(direction, points) for direction in
                       ('forward', 'back', 'left', 'right', 'turn_left', 'turn_right')}})
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
