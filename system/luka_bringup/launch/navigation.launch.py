from launch import LaunchDescription
from luka_bringup.navigation import navigation_actions

def generate_launch_description():
 return LaunchDescription(navigation_actions())
