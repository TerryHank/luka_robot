from launch import LaunchDescription
from launch_ros.actions import Node

def generate_launch_description():
 return LaunchDescription([Node(package='luka_bringup',executable='runtime_host',output='screen')])
