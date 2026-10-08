from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from luka_bringup.paths import workspace_root

def generate_launch_description():
 return LaunchDescription([IncludeLaunchDescription(PythonLaunchDescriptionSource(str(workspace_root()/'system/bringup/nx_sensors.launch.py')))])
