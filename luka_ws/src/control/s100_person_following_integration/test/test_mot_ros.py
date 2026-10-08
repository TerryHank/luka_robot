"""Official MOT transport and disappearance contract using synthetic fused inputs."""
import os
import signal
import subprocess
import time

os.environ['ROS_DOMAIN_ID'] = '97'
os.environ['ROS_LOCALHOST_ONLY'] = '1'
import rclpy
from ai_msgs.msg import PerceptionTargets, Target, Roi, Attribute


def test_official_mot_attributes_ids_and_disappearance(tmp_path):
    rclpy.init()
    node = rclpy.create_node('official_mot_contract_test')
    received = []
    publisher = node.create_publisher(PerceptionTargets, '/mot_test/input', 10)
    node.create_subscription(PerceptionTargets, '/mot_test/output', received.append, 10)
    prefix = '/home/sunrise/luka_ws'
    logfile = open(tmp_path / 'mot.log', 'w')
    process = subprocess.Popen([
        prefix + '/install/hobot_mot/lib/hobot_mot/tros_mot_node', '--ros-args',
        '-p', 'sub_topic:=/mot_test/input', '-p', 'pub_topic:=/mot_test/output',
        '-p', 'frame_width:=640', '-p', 'frame_height:=480', '-p',
        'mot_config_path:=' + prefix + '/src/control/tros_person_following/config/iou2_method_param.json'],
        stdout=logfile, stderr=subprocess.STDOUT)
    def emit(people):
        msg = PerceptionTargets()
        msg.header.frame_id = 'camera_link'
        msg.header.stamp = node.get_clock().now().to_msg()
        for x in people:
            target = Target(type='person')
            roi = Roi(type='person', confidence=0.95)
            roi.rect.x_offset, roi.rect.y_offset = x, 50
            roi.rect.width, roi.rect.height = 100, 300
            target.rois = [roi]
            target.attributes = [Attribute(type='x_cm', value=float(x)),
                                 Attribute(type='y_cm', value=10.0),
                                 Attribute(type='width_cm', value=50.0),
                                 Attribute(type='height_cm', value=170.0)]
            msg.targets.append(target)
        publisher.publish(msg)
        end = time.monotonic() + 0.05
        while time.monotonic() < end: rclpy.spin_once(node, timeout_sec=0.01)
    try:
        end = time.monotonic() + 1.0
        while time.monotonic() < end: rclpy.spin_once(node, timeout_sec=0.05)
        for _ in range(20): emit([100, 400])
        assert process.poll() is None and received
        tracked = [m for m in received if len(m.targets) == 2]
        assert len(tracked) >= 10
        ids = [tuple(t.track_id for t in m.targets) for m in tracked]
        assert len(set(ids)) == 1 and ids[-1][0] != ids[-1][1]
        for message in tracked:
            assert message.header.frame_id == 'camera_link' and message.header.stamp.sec > 0
            assert {t.attributes[0].value for t in message.targets} == {100.0, 400.0}
            assert all(len(t.attributes) == 4 and t.rois[0].type == 'person' for t in message.targets)
        received.clear()
        for _ in range(100): emit([])
        vanished = {t.track_id for message in received for t in message.disappeared_targets}
        assert set(ids[-1]) <= vanished, 'Empty detections must age the known trackers and report disappearance'
    finally:
        process.send_signal(signal.SIGINT)
        try: process.wait(5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        node.destroy_node()
        rclpy.shutdown()
        logfile.close()
