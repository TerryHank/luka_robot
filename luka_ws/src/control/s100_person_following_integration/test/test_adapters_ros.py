"""Transport verification of format conversion and fail-closed timestamp pairing."""
import os
import signal
import subprocess
import time

os.environ['ROS_DOMAIN_ID'] = '95'
os.environ['ROS_LOCALHOST_ONLY'] = '1'
import cv2
import numpy as np
import rclpy
from ai_msgs.msg import PerceptionTargets, Target, Capture
from sensor_msgs.msg import Image
from std_msgs.msg import Float64


def test_geometry_headers_pair_skew_and_invalid_inputs(tmp_path):
    rclpy.init()
    node = rclpy.create_node('adapter_transport_test')
    converted, paired, skews = [], [], []
    color = node.create_publisher(Image, '/adapter_test/color', 10)
    depth = node.create_publisher(Image, '/adapter_test/depth', 10)
    seg = node.create_publisher(PerceptionTargets, '/adapter_test/seg', 10)
    node.create_subscription(Image, '/adapter_test/nv12', converted.append, 10)
    node.create_subscription(Image, '/person_follow/fusion/depth', paired.append, 10)
    node.create_subscription(Float64, '/person_follow/pair_skew_sec', skews.append, 10)
    base = '/home/sunrise/luka_ws/install/s100_person_following_integration/lib/s100_person_following_integration/'
    logs = [open(tmp_path / name, 'w') for name in ['convert.log', 'pair.log']]
    processes = [subprocess.Popen([base + 'rgb_to_nv12.py', '--ros-args',
                                  '-p', 'input_topic:=/adapter_test/color', '-p', 'output_topic:=/adapter_test/nv12'],
                                 stdout=logs[0], stderr=subprocess.STDOUT),
                 subprocess.Popen([base + 'pair_registered_depth.py', '--ros-args',
                                   '-p', 'depth_topic:=/adapter_test/depth', '-p', 'seg_topic:=/adapter_test/seg'],
                                  stdout=logs[1], stderr=subprocess.STDOUT)]
    def wait(seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end: rclpy.spin_once(node, timeout_sec=0.02)
        assert all(p.poll() is None for p in processes)
    def packet(offset=0.02, fault=None):
        msg = Image()
        msg.header.stamp = node.get_clock().now().to_msg()
        msg.header.frame_id = 'camera_color_optical_frame'
        msg.width, msg.height, msg.step, msg.encoding = 320, 240, 640, '16UC1'
        msg.data = np.full((240, 320), 2000, dtype='<u2').tobytes()
        targets = PerceptionTargets()
        targets.header.frame_id = msg.header.frame_id
        stamp_ns = msg.header.stamp.sec * 1000000000 + msg.header.stamp.nanosec + int(offset * 1e9)
        targets.header.stamp.sec, targets.header.stamp.nanosec = divmod(stamp_ns, 1000000000)
        capture = Capture()
        capture.img.width, capture.img.height = 80, 60
        capture.features = [1.0] * 4800
        targets.targets = [Target(type='parking_space', captures=[capture])]
        if fault == 'box_only': targets.targets = [Target(type='person')]
        if fault == 'nan_mask': capture.features[0] = float('nan')
        if fault == 'frame': targets.header.frame_id = 'wrong_optical_frame'
        if fault == 'depth_length': msg.data = bytes(2)
        if fault == 'stale':
            msg.header.stamp.sec -= 2
            targets.header.stamp.sec -= 2
        depth.publish(msg)
        seg.publish(targets)
        return msg, targets
    try:
        wait(1.5)
        rgb = np.zeros((240, 320, 3), dtype=np.uint8)
        rgb[:, :, 0] = 255
        image = Image()
        image.header.stamp = node.get_clock().now().to_msg()
        image.header.frame_id = 'camera_color_optical_frame'
        image.width, image.height, image.step, image.encoding = 320, 240, 960, 'rgb8'
        image.data = rgb.tobytes()
        color.publish(image)
        wait(0.3)
        assert converted
        output = converted[-1]
        assert output.width == 320 and output.height == 240 and output.step == 320
        assert output.encoding == 'nv12' and output.header == image.header
        decoded = cv2.cvtColor(np.asarray(output.data, dtype=np.uint8).reshape(360, 320), cv2.COLOR_YUV2RGB_NV12)
        assert np.mean(np.abs(decoded.astype(float) - rgb)) < 3
        original, target = packet()
        wait(0.3)
        assert paired and skews
        assert paired[-1].header.stamp == target.header.stamp
        assert paired[-1].header.frame_id == original.header.frame_id
        assert paired[-1].data == original.data
        assert abs(skews[-1].data + 0.02) < 1e-5
        for fault in ['skew', 'box_only', 'nan_mask', 'frame', 'depth_length', 'stale']:
            paired.clear()
            packet(offset=0.1 if fault == 'skew' else 0.01, fault=fault)
            wait(0.3)
            assert not paired, fault
    finally:
        for p in processes:
            p.send_signal(signal.SIGINT)
            try: p.wait(5)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
        node.destroy_node()
        rclpy.shutdown()
        for f in logs: f.close()
