"""RGB-D experiment: consume camera topics, never publish production TF or goals."""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, SetEnvironmentVariable
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    common = {
        'frame_id': LaunchConfiguration('camera_frame'),
        'publish_tf': True,
        'approx_sync': True,
        'approx_sync_max_interval': 0.06,
        'topic_queue_size': 5,
        'sync_queue_size': 10,
        'qos': 2,
        'qos_camera_info': 2,
        'wait_for_transform': 0.2,
    }
    images = [('rgb/image', LaunchConfiguration('rgb_topic')),
              ('depth/image', LaunchConfiguration('depth_topic')),
              ('rgb/camera_info', LaunchConfiguration('camera_info_topic')),
              ('/tf', '/rtabmap_rgbd/tf')]
    return LaunchDescription([
        DeclareLaunchArgument('database_path'),
        DeclareLaunchArgument('camera_frame', default_value='camera_link'),
        DeclareLaunchArgument('rgb_topic', default_value='/camera/color/image_raw'),
        DeclareLaunchArgument('depth_topic', default_value='/camera/depth/image_raw'),
        DeclareLaunchArgument('camera_info_topic', default_value='/camera/color/camera_info'),
        SetEnvironmentVariable('OMP_NUM_THREADS', '2'),
        SetEnvironmentVariable('OPENBLAS_NUM_THREADS', '1'),
        Node(package='rtabmap_odom', executable='rgbd_odometry',
             name='rgbd_odometry', namespace='rtabmap_rgbd', output='screen',
             parameters=[dict(common, odom_frame_id='rtabmap_rgbd_odom'),
                         {'Odom/ImageDecimation': '2', 'Vis/MaxFeatures': '500',
                          'OdomF2M/MaxSize': '1000'}],
             remappings=images),
        Node(package='rtabmap_slam', executable='rtabmap',
             name='rtabmap', namespace='rtabmap_rgbd', output='screen',
             parameters=[common, {'subscribe_depth': True, 'subscribe_rgb': True,
                         'odom_frame_id': '', 'map_frame_id': 'rtabmap_rgbd_map',
                         'database_path': LaunchConfiguration('database_path'),
                         'Rtabmap/DetectionRate': '1.0', 'Mem/IncrementalMemory': 'true',
                         'RGBD/LinearUpdate': '0.05', 'RGBD/AngularUpdate': '0.05',
                         'Grid/FromDepth': 'true', 'Grid/RangeMax': '4.0'}],
             remappings=images + [('odom', 'odom')]),
    ])
