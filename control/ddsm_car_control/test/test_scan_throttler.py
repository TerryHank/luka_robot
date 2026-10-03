from builtin_interfaces.msg import Time
from rclpy.qos import ReliabilityPolicy
from sensor_msgs.msg import LaserScan

from ddsm_car_control.scan_throttler import (
    prepare_scan_for_publish,
    scan_publish_qos,
    should_publish_scan,
)


def test_should_publish_first_scan_immediately():
    assert should_publish_scan(None, now_seconds=10.0, publish_period=0.5)


def test_should_hold_scan_until_publish_period_elapsed():
    assert not should_publish_scan(10.0, now_seconds=10.2, publish_period=0.5)
    assert should_publish_scan(10.0, now_seconds=10.5, publish_period=0.5)


def test_should_publish_all_scans_when_period_is_disabled():
    assert should_publish_scan(10.0, now_seconds=10.01, publish_period=0.0)


def test_scan_publish_qos_is_reliable_for_slam_toolbox_compatibility():
    assert scan_publish_qos().reliability == ReliabilityPolicy.RELIABLE


def test_prepare_scan_for_publish_restamps_scan_to_publish_time():
    scan = LaserScan()
    scan.header.frame_id = "laser"
    scan.header.stamp.sec = 1
    scan.header.stamp.nanosec = 2

    publish_stamp = Time(sec=10, nanosec=20)
    prepared = prepare_scan_for_publish(scan, publish_stamp)

    assert prepared.header.frame_id == "laser"
    assert prepared.header.stamp.sec == 10
    assert prepared.header.stamp.nanosec == 20
