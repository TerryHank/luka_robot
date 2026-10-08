from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration, PythonExpression
from launch_ros.actions import Node


def generate_launch_description():
    dry = LaunchConfiguration('dry_run')
    mode = LaunchConfiguration('tracking_mode')
    mot_enabled = IfCondition(PythonExpression([
        "'", mode, "' == 'automatic'"
    ]))
    gate_input = PythonExpression([
        "'/luka/perception/mot_targets' if '", mode,
        "' == 'automatic' else '/luka/perception/person_targets'"
    ])
    return LaunchDescription([
        DeclareLaunchArgument('dry_run', default_value='true', choices=['true', 'false']),
        DeclareLaunchArgument(
            'tracking_mode', default_value='selected',
            choices=['selected', 'automatic']),
        DeclareLaunchArgument(
            'status_url',
            default_value='http://127.0.0.1:8098/api/people/follow-state'),
        DeclareLaunchArgument(
            'selection_topic', default_value='/luka/perception/selected_track_id'),
        DeclareLaunchArgument(
            'auto_select_first_person', default_value='false',
            choices=['true', 'false']),
        DeclareLaunchArgument(
            'publish_camera_mount', default_value='true',
            choices=['true', 'false']),

        Node(
            package='tf2_ros',
            executable='static_transform_publisher',
            name='body_ground_projection',
            condition=IfCondition(LaunchConfiguration('publish_camera_mount')),
            arguments=[
                '--x','0','--y','0','--z','0',
                '--roll','0','--pitch','0','--yaw','0',
                '--frame-id','base_link','--child-frame-id','base_footprint']),

        Node(
            package='tf2_ros',
            executable='static_transform_publisher',
            name='astra_body_mount',
            condition=IfCondition(LaunchConfiguration('publish_camera_mount')),
            arguments=[
                '--x','0','--y','0','--z','0.70',
                '--roll','0','--pitch','0','--yaw','0',
                '--frame-id','base_footprint','--child-frame-id','camera_link']),

        # Official MOT is intentionally exclusive to automatic/demo mode.
        # selected mode keeps Luka's selected/identity tracker authoritative.
        Node(
            package='hobot_mot',
            executable='tros_mot_node',
            name='luka_automatic_mot',
            condition=mot_enabled,
            output='screen',
            parameters=[{
                'sub_topic': '/luka/perception/person_targets',
                'pub_topic': '/luka/perception/mot_targets',
                'mot_config_path': 'config/iou2_method_param.json',
                'frame_width': 640,
                'frame_height': 480,
            }]),

        Node(
            package='luka_person_following',
            executable='selected_bridge',
            output='screen',
            parameters=[{
                'status_url': LaunchConfiguration('status_url'),
                'tracking_mode': mode,
                'perception_topic': gate_input,
                'selection_topic': LaunchConfiguration('selection_topic'),
                'output_topic': '/luka/follow/selected_target',
                'legacy_output_topic': '/luka/selected_seg_targets',
                'auto_select_first_person':
                    LaunchConfiguration('auto_select_first_person'),
            }]),

        Node(
            package='tros_person_following',
            executable='tros_person_following',
            namespace='luka_person_following/official',
            output='screen',
            parameters=[{
                'detect_result_topic_name': '/luka/follow/selected_target',
                'image_width': 640.0,
                'global_frame': 'map',
                'robot_frame': 'base_footprint',
                'target_filter_range_x_max': 4.0,
                'target_filter_range_y_min': -3.0,
                'target_filter_range_y_max': 3.0,
                'follow_distance_min': 1.8,
                'follow_distance_max': 2.0,
                'follow_hysteresis': 0.1,
                'follow_min_safe_distance': 0.5,
                'follow_goal_pub_rate': 2.5,
                'follow_goal_dist_deadzone': 0.3,
                'follow_goal_yaw_deadzone': 0.6,
                'tracking_to_lost_timeout_sec': 1.0,
                'lost_to_idle_timeout_sec': 5.0,
                'idle_search_total_timeout_sec': 0.0,
                'navigate_to_pose_action_name': PythonExpression([
                    "'/luka_follow_dryrun/navigate_to_pose' if '",
                    dry,
                    "' == 'true' else '/luka/behavior/follow_navigation'"
                ]),
                'cmd_vel_topic': PythonExpression([
                    "'/luka_follow_dryrun/cmd_vel' if '",
                    dry,
                    "' == 'true' else '/luka/motion/follow'"
                ]),
            }],
            remappings=[
                ('/buzzer_pattern', '/luka_follow_dryrun/buzzer_pattern'),
                ('enable_blind_zone_observing',
                 '/luka_follow_dryrun/enable_blind_zone_observing'),
            ]),
    ])
