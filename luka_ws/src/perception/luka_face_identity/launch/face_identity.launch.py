from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    # Reuse existing camera and official MOT; never start a second perception/motion stack.
    return LaunchDescription([Node(package='luka_face_identity', executable='face_identity',
                                   output='screen', parameters=[{'enable_face': False}])])
