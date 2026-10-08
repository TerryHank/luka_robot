"""Reuse camera/TF/Nav2; start only explicitly selected official perception nodes."""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def setup(context):
    def value(name):
        return LaunchConfiguration(name).perform(context)

    def flag(name):
        v = value(name).lower()
        if v not in ('true', 'false'):
            raise RuntimeError(name + ' must be true or false')
        return v == 'true'

    mode = value('output_mode')
    if mode not in ('dry_run', 'nav2_action'):
        raise RuntimeError('output_mode must be dry_run or nav2_action')
    if mode == 'nav2_action' and not flag('input_contract_verified'):
        raise RuntimeError('Validate live segmentation/depth/TF before setting input_contract_verified=true')
    share = get_package_share_directory('s100_person_following_integration')
    selected = []
    topics = []
    if flag('start_segmentation'):
        get_package_share_directory('dnn_node_example')
        config = value('segmentation_config')
        if not os.path.isfile(config):
            raise RuntimeError('Missing S100 model configuration: ' + config)
        selected.append(Node(package='s100_person_following_integration', executable='rgb_to_nv12.py',
                             parameters=[{'input_topic': value('image_topic'),
                                          'output_topic': '/person_follow/image_nv12'}]))
        selected.append(Node(package='dnn_node_example', executable='example',
                             name='s100_official_segmentation', output='screen',
                             parameters=[{'feed_type': 1, 'is_shared_mem_sub': 0,
                                          'config_file': config,
                                          'ros_img_topic_name': '/person_follow/image_nv12',
                                          'msg_pub_topic_name': value('segmentation_topic'),
                                          'dump_render_img': 0}]))
        topics.append(value('segmentation_topic'))
        topics.append('/person_follow/image_nv12')
    width, height = int(value('image_width')), int(value('image_height'))
    if width <= 0 or height <= 0:
        raise RuntimeError('Invalid image dimensions')
    if flag('start_depth_fusion'):
        get_package_share_directory('hobot_obstacle_depth_fusion')
        selected.append(Node(package='s100_person_following_integration', executable='pair_registered_depth.py',
                             parameters=[{'depth_topic': value('depth_topic'),
                                          'seg_topic': value('segmentation_topic')}]))
        selected.append(Node(package='hobot_obstacle_depth_fusion',
                             executable='hobot_obstacle_depth_fusion', output='screen',
                             parameters=[{
                                 'depth_msg_topic': '/person_follow/fusion/depth',
                                 'seg_result_msg_topic': '/person_follow/fusion/seg',
                                 'seg_result_info_msg_topic': value('segmentation_topic') + '_info',
                                 'pub_fusion_msg_topic_seg': value('fusion_topic'),
                                 'camera_info_rect_topic': value('camera_info_topic'),
                                 'detect_mode': 2,
                                 'detect_input_width': width, 'detect_input_height': height,
                                 'seg_output_width': width, 'seg_output_height': height,
                                 'seg_valid_labels': '1',
                                 'enable_pub_ai_with_depth': True,
                                 # VIMS 0.0.6 crashes in depth_to_point_cloud when false.
                                 # Keep its internal grid enabled on an isolated debug topic.
                                 'enable_pub_map': True, 'enable_pcl_cvt_seg': False,
                                 'occ_map_msg_topic_seg': '/person_follow/fusion/debug_map',
                                 'occ_map_msg_topic_detect': '/person_follow/fusion/debug_detect_map',
                                 'point_cloud_target_frame': value('camera_frame'),
                                 'occ_map_target_frame': value('camera_frame'),
                                 'enable_dbg_seg': False, 'enable_tros_perf': False,
                                 'max_obstacle_depth': 5.0, 'depth_hight_threshold': 10.1,
                                 'ground_upper_bound': 10.0, 'ground_lower_bound': -10.0,
                                 'depth_vaild_area': 1.0, 'seg_filter_max_area_ratio': 0.92,
                                 'seg_filter_max_depth_diff': 300, 'seg_map_depth_count': 1,
                             }]))
        topics.append(value('fusion_topic'))
        topics.extend(['/person_follow/fusion/depth', '/person_follow/fusion/seg'])
    if flag('start_mot'):
        selected.append(Node(package='hobot_mot', executable='tros_mot_node', output='screen',
                             parameters=[{'sub_topic': value('fusion_topic'),
                                          'pub_topic': value('detect_result_topic'),
                                          'mot_config_path': os.path.join(get_package_share_directory('tros_person_following'), 'config', 'iou2_method_param.json'),
                                          'frame_width': width, 'frame_height': height}]))
        topics.append(value('detect_result_topic'))
    # A fresh graph check, without using the CLI daemon cache.
    import rclpy
    from rclpy.context import Context
    from rclpy.executors import SingleThreadedExecutor
    from rclpy.node import Node as Probe
    import time
    probe_context = Context()
    rclpy.init(args=[], context=probe_context)
    probe = Probe('person_follow_launch_probe', context=probe_context)
    executor = SingleThreadedExecutor(context=probe_context)
    executor.add_node(probe)
    try:
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            executor.spin_once(timeout_sec=0.1)
        for topic in topics:
            if probe.count_publishers(topic):
                raise RuntimeError('Already published; set corresponding start flag false: ' + topic)
        if any('tros_person_following' in name for name, _ in probe.get_node_names_and_namespaces()):
            raise RuntimeError('A person follower already exists; stop it before starting another')
    finally:
        executor.shutdown()
        probe.destroy_node()
        rclpy.shutdown(context=probe_context)
    if flag('start_person_following'):
        selected.append(Node(package='tros_person_following', executable='tros_person_following',
                             namespace='person_follow', output='screen',
                             remappings=[('enable_blind_zone_observing', '/enable_blind_zone_observing')],
                             parameters=[os.path.join(share, 'config', 'person_following_s100.yaml'), {
                                 'output_mode': mode,
                                 'follow_enabled_on_start': flag('follow_enabled_on_start'),
                                 'global_frame': value('global_frame'),
                                 'robot_frame': value('robot_frame'),
                                 'camera_frame': value('camera_frame'),
                                 'detect_result_topic_name': value('detect_result_topic'),
                                 'costmap_topic': value('costmap_topic'),
                                 'navigate_to_pose_action_name': value('navigate_action'),
                             }], arguments=['--ros-args', '--log-level', value('log_level')]))
    return selected


def generate_launch_description():
    args = {
        'start_segmentation': 'false', 'start_depth_fusion': 'true', 'start_mot': 'true',
        'start_person_following': 'true', 'output_mode': 'dry_run',
        'follow_enabled_on_start': 'false', 'input_contract_verified': 'false',
        'global_frame': 'map', 'robot_frame': 'base_link', 'camera_frame': 'camera_link',
        'image_topic': '/camera/color/image_raw', 'depth_topic': '/camera/depth/image_raw',
        'camera_info_topic': '/camera/color/camera_info', 'image_width': '640', 'image_height': '480',
        'segmentation_topic': '/hobot_dnn_seg', 'fusion_topic': '/tros_fusion_interaction',
        'detect_result_topic': '/tros_mot_targets', 'costmap_topic': '/global_costmap/costmap',
        'navigate_action': '/navigate_to_pose', 'log_level': 'info',
        'segmentation_config': '/home/sunrise/luka_ws/src/control/s100_person_following_integration/config/yolov8seg_s100.json',
    }
    return LaunchDescription([DeclareLaunchArgument(k, default_value=v) for k, v in args.items()] +
                             [OpaqueFunction(function=setup)])
