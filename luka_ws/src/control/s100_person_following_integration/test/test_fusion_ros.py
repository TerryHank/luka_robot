"""Synthetic masks and metric depth through the official binary, no physical navigation."""
import json
import os
import signal
import subprocess
import time

os.environ['ROS_DOMAIN_ID'] = '96'
os.environ['ROS_LOCALHOST_ONLY'] = '1'
import numpy as np
import rclpy
from ai_msgs.msg import PerceptionTargets, PerceptionInfo, Target, Capture, Attribute
from sensor_msgs.msg import Image, CameraInfo
from geometry_msgs.msg import TransformStamped
from tf2_ros import StaticTransformBroadcaster


def test_official_fusion_depth_scale_and_lateral_sign(tmp_path):
    rclpy.init()
    node = rclpy.create_node('fusion_contract_test')
    result = []
    pubs = [node.create_publisher(t, name, 10) for t, name in
            [(Image, '/fusion_test/depth'), (CameraInfo, '/fusion_test/info'),
             (PerceptionTargets, '/fusion_test/seg'), (PerceptionInfo, '/fusion_test/seg_info')]]
    node.create_subscription(PerceptionTargets, '/fusion_test/output', result.append, 10)
    broadcaster = StaticTransformBroadcaster(node)
    tf = TransformStamped()
    tf.header.frame_id, tf.child_frame_id = 'camera_link', 'camera_color_optical_frame'
    tf.transform.rotation.x, tf.transform.rotation.y = -0.5, 0.5
    tf.transform.rotation.z, tf.transform.rotation.w = -0.5, 0.5
    broadcaster.sendTransform(tf)
    exe = '/home/sunrise/luka_upstream/vims-fusion-0.0.6/install/lib/hobot_obstacle_depth_fusion/hobot_obstacle_depth_fusion'
    params = {'depth_msg_topic': '/fusion_test/depth', 'camera_info_rect_topic': '/fusion_test/info',
              'seg_result_msg_topic': '/fusion_test/seg', 'seg_result_info_msg_topic': '/fusion_test/seg_info',
              'pub_fusion_msg_topic_seg': '/fusion_test/output', 'detect_mode': 2,
              'detect_input_width': 640, 'detect_input_height': 480,
              'seg_output_width': 640, 'seg_output_height': 480,
              'enable_pub_ai_with_depth': True, 'enable_pcl_cvt_seg': False,
              'enable_pub_map': True, 'point_cloud_target_frame': 'camera_link',
              'occ_map_msg_topic_seg': '/fusion_test/debug_map',
              'occ_map_target_frame': 'camera_link', 'seg_valid_labels': '1',
              'ground_upper_bound': 10.0, 'ground_lower_bound': -10.0,
              'depth_hight_threshold': 10.1, 'max_obstacle_depth': 5.0, 'depth_vaild_area': 1.0}
    # Parameter file preserves string "1", unlike ROS CLI YAML inference.
    import yaml
    config = tmp_path / 'fusion.yaml'
    config.write_text(yaml.safe_dump({'/**': {'ros__parameters': params}}))
    logfile = open(tmp_path / 'fusion.log', 'w')
    command = [exe, '--ros-args', '--params-file', str(config)]
    if os.environ.get('FUSION_GDB'):
        command = ['gdb', '-batch', '-ex', 'run', '-ex', 'bt', '--args'] + command
    process = subprocess.Popen(command,
                               stdout=logfile, stderr=subprocess.STDOUT)
    def emit(depth_mm, center):
        stamp = node.get_clock().now().to_msg()
        header_frame = 'camera_color_optical_frame'
        depth = Image()
        depth.header.stamp, depth.header.frame_id = stamp, header_frame
        depth.width, depth.height, depth.encoding, depth.step = 640, 480, '16UC1', 1280
        depth.data = np.full((480, 640), depth_mm, dtype='<u2').tobytes()
        info = CameraInfo()
        info.header = depth.header
        info.width, info.height = 640, 480
        info.k = [500.0, 0.0, 320.0, 0.0, 500.0, 240.0, 0.0, 0.0, 1.0]
        info.p = [500.0, 0.0, 320.0, 0.0, 0.0, 500.0, 240.0, 0.0, 0.0, 0.0, 1.0, 0.0]
        segmentation = PerceptionTargets()
        segmentation.header = depth.header
        target = Target(type='parking_space')
        target.attributes = [Attribute(type='segmentation_label_count', value=80.0)]
        capture = Capture()
        capture.img.width, capture.img.height, capture.img.step = 160, 120, 1
        mask = np.zeros((120, 160), dtype=np.float32)
        mask[25:105, center-15:center+15] = 1.0
        capture.features = mask.reshape(-1).tolist()
        target.captures = [capture]
        segmentation.targets = [target]
        seg_info = PerceptionInfo()
        seg_info.header = depth.header
        seg_info.width, seg_info.height = 640, 480
        names = '/home/sunrise/luka_upstream/s100-dnn/extracted/opt/tros/humble/lib/dnn_node_example/config/coco.list'
        seg_info.class_names = open(names).read().splitlines()
        for pub, msg in zip(pubs, [depth, info, segmentation, seg_info]): pub.publish(msg)
        end = time.monotonic() + 0.1
        while time.monotonic() < end: rclpy.spin_once(node, timeout_sec=0.01)
    samples = []
    try:
        end = time.monotonic() + 1.0
        while time.monotonic() < end: rclpy.spin_once(node, timeout_sec=0.05)
        for depth_mm, center in [(2000, 80), (3000, 60), (3000, 100)]:
            result.clear()
            for _ in range(15): emit(depth_mm, center)
            people = [t for m in result for t in m.targets if t.type == 'person']
            assert process.poll() is None and people, 'Official fusion must produce a spatial person from real mask/depth contracts'
            values = {a.type: a.value for a in people[-1].attributes}
            samples.append(values)
            assert abs(values['x_cm'] - depth_mm / 10) < 10
            assert values['width_cm'] > 0 and values['height_cm'] > 0
        assert samples[1]['y_cm'] > 0 and samples[2]['y_cm'] < 0
        (tmp_path / 'spatial_samples.json').write_text(json.dumps(samples, indent=2))
    finally:
        process.send_signal(signal.SIGINT)
        try: process.wait(5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        node.destroy_node()
        rclpy.shutdown()
        logfile.close()
