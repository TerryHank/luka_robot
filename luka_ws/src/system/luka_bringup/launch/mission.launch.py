"""MissionManager and BehaviorRegistry share one composition host, not two schedulers."""
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from ament_index_python.packages import get_package_share_directory
from pathlib import Path

def generate_launch_description():
 return LaunchDescription([IncludeLaunchDescription(PythonLaunchDescriptionSource(
   str(Path(get_package_share_directory('luka_bringup'))/'launch/behavior.launch.py')))])
