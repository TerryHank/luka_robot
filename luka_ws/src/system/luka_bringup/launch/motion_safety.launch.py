from launch import LaunchDescription
from luka_bringup.navigation import safety_actions

def generate_launch_description():
 return LaunchDescription(safety_actions())
