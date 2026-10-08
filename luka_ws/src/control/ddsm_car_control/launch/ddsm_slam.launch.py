#!/usr/bin/env python3

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, GroupAction, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node, SetRemap
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    host_arg = DeclareLaunchArgument(
        "host",
        default_value="192.168.3.139",
        description="ESP32 STA IP address",
    )
    command_port_arg = DeclareLaunchArgument(
        "command_port",
        default_value="9001",
        description="ESP32 UDP command port",
    )
    odom_port_arg = DeclareLaunchArgument(
        "odom_port",
        default_value="9000",
        description="Local UDP odom listen port",
    )
    cmd_freq_arg = DeclareLaunchArgument(
        "cmd_freq",
        default_value="20.0",
        description="UDP command send frequency in Hz",
    )
    slam_params_file_arg = DeclareLaunchArgument(
        "slam_params_file",
        default_value=PathJoinSubstitution(
            [
                FindPackageShare("ddsm_car_control"),
                "config",
                "slam_toolbox_mapping.yaml",
            ]
        ),
        description="Full path to slam_toolbox mapping parameter file",
    )
    ekf_params_file_arg = DeclareLaunchArgument(
        "ekf_params_file",
        default_value=PathJoinSubstitution(
            [FindPackageShare("ddsm_car_control"), "config", "ekf_imu_yaw_rate.yaml"]
        ),
        description="Full path to robot_localization EKF parameter file",
    )
    map_publish_frequency_arg = DeclareLaunchArgument(
        "map_publish_frequency",
        default_value="2.0",
        description="Public /map republish frequency in Hz for visualization",
    )

    robot_bringup = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            PathJoinSubstitution(
                [
                    FindPackageShare("ddsm_car_control"),
                    "launch",
                    "ddsm_robot_bringup.launch.py",
                ]
            )
        ),
        launch_arguments={
            "host": LaunchConfiguration("host"),
            "command_port": LaunchConfiguration("command_port"),
            "odom_port": LaunchConfiguration("odom_port"),
            "cmd_freq": LaunchConfiguration("cmd_freq"),
            "ekf_params_file": LaunchConfiguration("ekf_params_file"),
        }.items(),
    )

    slam_toolbox = GroupAction(
        [
            SetRemap(src="/map", dst="/slam_map"),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    PathJoinSubstitution(
                        [
                            FindPackageShare("slam_toolbox"),
                            "launch",
                            "online_async_launch.py",
                        ]
                    )
                ),
                launch_arguments={
                    "slam_params_file": LaunchConfiguration("slam_params_file"),
                    "use_sim_time": "false",
                    "autostart": "true",
                    "use_lifecycle_manager": "false",
                }.items(),
            ),
        ]
    )

    map_republisher = Node(
        package="ddsm_car_control",
        executable="map_republisher",
        name="map_republisher",
        output="screen",
        parameters=[
            {
                "input_topic": "/slam_map",
                "output_topic": "/map",
                "publish_frequency": LaunchConfiguration("map_publish_frequency"),
                "refresh_stamp": True,
            }
        ],
    )

    return LaunchDescription(
        [
            host_arg,
            command_port_arg,
            odom_port_arg,
            cmd_freq_arg,
            slam_params_file_arg,
            ekf_params_file_arg,
            map_publish_frequency_arg,
            robot_bringup,
            slam_toolbox,
            map_republisher,
        ]
    )
