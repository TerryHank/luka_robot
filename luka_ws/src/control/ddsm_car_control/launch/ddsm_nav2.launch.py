#!/usr/bin/env python3

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
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
    map_arg = DeclareLaunchArgument(
        "map",
        default_value="/home/sunrise/luka_data/maps/ddsm_map.yaml",
        description="Full path to the saved map YAML file",
    )
    params_file_arg = DeclareLaunchArgument(
        "params_file",
        default_value=PathJoinSubstitution(
            [FindPackageShare("ddsm_car_control"), "config", "nav2_params.yaml"]
        ),
        description="Full path to the Nav2 parameter file",
    )
    ekf_params_file_arg = DeclareLaunchArgument(
        "ekf_params_file",
        default_value=PathJoinSubstitution(
            [FindPackageShare("ddsm_car_control"), "config", "ekf_imu_yaw_rate.yaml"]
        ),
        description="Full path to robot_localization EKF parameter file",
    )
    autostart_arg = DeclareLaunchArgument(
        "autostart",
        default_value="true",
        description="Automatically transition Nav2 lifecycle nodes to active",
    )
    use_composition_arg = DeclareLaunchArgument(
        "use_composition",
        default_value="False",
        description="Use composed Nav2 bringup if true",
    )
    use_respawn_arg = DeclareLaunchArgument(
        "use_respawn",
        default_value="True",
        description="Respawn Nav2 processes if they exit",
    )
    log_level_arg = DeclareLaunchArgument(
        "log_level",
        default_value="info",
        description="Nav2 log level",
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

    nav2_localization = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            PathJoinSubstitution(
                [FindPackageShare("nav2_bringup"), "launch", "localization_launch.py"]
            )
        ),
        launch_arguments={
            "map": LaunchConfiguration("map"),
            "params_file": LaunchConfiguration("params_file"),
            "use_sim_time": "false",
            "autostart": LaunchConfiguration("autostart"),
            "use_composition": LaunchConfiguration("use_composition"),
            "use_respawn": LaunchConfiguration("use_respawn"),
            "log_level": LaunchConfiguration("log_level"),
        }.items(),
    )

    nav2_navigation = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            PathJoinSubstitution(
                [FindPackageShare("nav2_bringup"), "launch", "navigation_launch.py"]
            )
        ),
        launch_arguments={
            "params_file": LaunchConfiguration("params_file"),
            "use_sim_time": "false",
            "autostart": "false",
            "use_composition": LaunchConfiguration("use_composition"),
            "use_respawn": LaunchConfiguration("use_respawn"),
            "log_level": LaunchConfiguration("log_level"),
        }.items(),
    )

    navigation_autostarter = Node(
        package="ddsm_car_control",
        executable="nav_lifecycle_autostarter",
        name="nav_lifecycle_autostarter",
        output="screen",
        parameters=[
            {
                "map_frame": "map",
                "odom_frame": "odom",
                "manager_service": "/lifecycle_manager_navigation/manage_nodes",
                "check_period": 1.0,
            }
        ],
    )

    return LaunchDescription(
        [
            host_arg,
            command_port_arg,
            odom_port_arg,
            cmd_freq_arg,
            map_arg,
            params_file_arg,
            ekf_params_file_arg,
            autostart_arg,
            use_composition_arg,
            use_respawn_arg,
            log_level_arg,
            robot_bringup,
            nav2_localization,
            nav2_navigation,
            navigation_autostarter,
        ]
    )
