import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, PythonExpression
from launch.conditions import IfCondition
from launch_ros.actions import Node


def generate_launch_description():
    dry = LaunchConfiguration('dry_run')
    relock_config = os.path.join(get_package_share_directory('luka_person_following'),
                                 'config', 'target_relock.yaml')
    return LaunchDescription([
        DeclareLaunchArgument('dry_run', default_value='true', choices=['true', 'false']),
        DeclareLaunchArgument('status_url', default_value='http://127.0.0.1:8098/api/people/follow-state'),
        DeclareLaunchArgument('auto_select_first_person', default_value='true', choices=['true', 'false']),
        DeclareLaunchArgument('publish_camera_mount', default_value='true', choices=['true', 'false']),
        # The installed planar odometry publishes base_link at ground height (z=0).
        Node(package='tf2_ros', executable='static_transform_publisher', name='body_ground_projection',
             condition=IfCondition(LaunchConfiguration('publish_camera_mount')),
             arguments=['--x','0','--y','0','--z','0','--roll','0','--pitch','0','--yaw','0',
                        '--frame-id','base_link','--child-frame-id','base_footprint']),
        # User confirmed: ground-projected body center, 0.70 m height, forward and level.
        Node(package='tf2_ros', executable='static_transform_publisher', name='astra_body_mount',
             condition=IfCondition(LaunchConfiguration('publish_camera_mount')),
             arguments=['--x','0','--y','0','--z','0.70','--roll','0','--pitch','0','--yaw','0',
                        '--frame-id','base_footprint','--child-frame-id','camera_link']),
        Node(package='luka_person_following', executable='selected_bridge', output='screen',
             parameters=[relock_config, {'status_url': LaunchConfiguration('status_url'),
                           'auto_select_first_person': LaunchConfiguration('auto_select_first_person')}]),
        Node(package='tros_person_following', executable='tros_person_following',
             namespace='luka_person_following/official', output='screen',
             parameters=[{'detect_result_topic_name': '/luka/selected_seg_targets',
                          'image_width': 640.0, 'global_frame': 'map', 'robot_frame': 'base_footprint',
                          'target_filter_range_x_max': 4.0,
                          'target_filter_range_y_min': -3.0, 'target_filter_range_y_max': 3.0,
                          'follow_distance_min': 1.8, 'follow_distance_max': 2.0,
                          'idle_search_total_timeout_sec': 0.0,
                          'navigate_to_pose_action_name': PythonExpression(["'/luka_follow_dryrun/navigate_to_pose' if '", dry, "' == 'true' else '/navigate_to_pose'"]),
                          'cmd_vel_topic': PythonExpression(["'/luka_follow_dryrun/cmd_vel' if '", dry, "' == 'true' else '/nx/follow_safe'"])}],
             remappings=[('/buzzer_pattern', '/luka_follow_dryrun/buzzer_pattern'),
                         ('enable_blind_zone_observing', '/luka_follow_dryrun/enable_blind_zone_observing')]),
    ])
