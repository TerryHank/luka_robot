from launch import LaunchDescription
from launch_ros.actions import Node
from luka_bringup.paths import workspace_root

def generate_launch_description():
 return LaunchDescription([Node(package='luka_base_gate',executable='base_gate',
   parameters=[str(workspace_root()/'common/config/nx_manual_base.yaml')],remappings=[('odom','/wheel/odom')],output='screen')])
