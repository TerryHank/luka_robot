from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument,ExecuteProcess
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from luka_bringup.paths import workspace_root

def generate_launch_description():
 root=workspace_root()
 return LaunchDescription([
   DeclareLaunchArgument('enable_agent',default_value='false'),
   DeclareLaunchArgument('enable_voice',default_value='false'),
   ExecuteProcess(cmd=['/bin/bash',str(root/'system/bringup/start_nx_agent.sh')],condition=IfCondition(LaunchConfiguration('enable_agent')),output='screen'),
   ExecuteProcess(cmd=['/bin/bash',str(root/'system/bringup/start_nx_voice.sh')],condition=IfCondition(LaunchConfiguration('enable_voice')),output='screen')])
