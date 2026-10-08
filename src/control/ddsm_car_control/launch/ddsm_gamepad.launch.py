from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    params_file = LaunchConfiguration("params_file")

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "params_file",
                default_value=PathJoinSubstitution(
                    [
                        FindPackageShare("ddsm_car_control"),
                        "config",
                        "flydigi_vader4pro.yaml",
                    ]
                ),
                description="Gamepad and joy_node parameter YAML",
            ),
            Node(
                package="joy",
                executable="joy_node",
                name="joy_node",
                output="screen",
                parameters=[params_file],
            ),
            Node(
                package="ddsm_car_control",
                executable="gamepad_teleop",
                name="gamepad_teleop",
                output="screen",
                parameters=[params_file],
            ),
        ]
    )
