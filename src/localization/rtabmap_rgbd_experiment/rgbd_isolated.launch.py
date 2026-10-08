"""Compatibility entrypoint; canonical graph lives in luka_visual_slam."""
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from ament_index_python.packages import get_package_share_directory
import os

def generate_launch_description():
    return LaunchDescription([IncludeLaunchDescription(PythonLaunchDescriptionSource(os.path.join(get_package_share_directory("luka_visual_slam"),"launch","visual_slam.launch.py")))])
