from pathlib import Path
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument,IncludeLaunchDescription,SetEnvironmentVariable,TimerAction
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch.launch_description_sources import PythonLaunchDescriptionSource
from luka_bringup.paths import workspace_root

def generate_launch_description():
 launch=Path(get_package_share_directory('luka_bringup'))/'launch'
 def include(name,condition=None):
  return IncludeLaunchDescription(PythonLaunchDescriptionSource(str(launch/(name+'.launch.py'))),condition=condition)
 return LaunchDescription([
   DeclareLaunchArgument('workspace_root',default_value=str(workspace_root())),
   DeclareLaunchArgument('enable_perception',default_value='false'),
   DeclareLaunchArgument('enable_agent',default_value='false'),
   DeclareLaunchArgument('enable_voice',default_value='false'),
   SetEnvironmentVariable('LUKA_WORKSPACE_ROOT',LaunchConfiguration('workspace_root')),
   SetEnvironmentVariable('LUKA_XIAOZHI_ALLOW_MOTION','0'),
   include('hardware'),
   TimerAction(period=1.,actions=[include('sensing')]),
   TimerAction(period=2.,actions=[include('localization')]),
   TimerAction(period=3.,actions=[include('perception',IfCondition(LaunchConfiguration('enable_perception')))]),
   TimerAction(period=4.,actions=[include('motion_safety')]),
   TimerAction(period=5.,actions=[include('navigation')]),
   TimerAction(period=6.,actions=[include('mission')]),
   TimerAction(period=7.,actions=[include('interaction')])])
