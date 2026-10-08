#!/usr/bin/env python3

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    port_arg = DeclareLaunchArgument(
        "port",
        default_value="/dev/ttyUSB0",
        description="WIT IMU serial port",
    )
    baud_arg = DeclareLaunchArgument(
        "baud",
        default_value="921600",
        description="WIT IMU baud rate",
    )
    protocol_arg = DeclareLaunchArgument(
        "protocol",
        default_value="normal",
        description="WIT protocol: normal or modbus",
    )
    frame_id_arg = DeclareLaunchArgument(
        "frame_id",
        default_value="base_link",
        description="Frame id used in IMU messages",
    )
    configure_output_arg = DeclareLaunchArgument(
        "configure_output",
        default_value="true",
        description="Send WIT standard-protocol output-enable command on startup",
    )

    node = Node(
        package="ddsm_car_control",
        executable="wit_imu_node",
        name="wit_imu_node",
        output="screen",
        parameters=[
            {
                "port": LaunchConfiguration("port"),
                "baud": ParameterValue(LaunchConfiguration("baud"), value_type=int),
                "protocol": LaunchConfiguration("protocol"),
                "frame_id": LaunchConfiguration("frame_id"),
                "configure_output": ParameterValue(
                    LaunchConfiguration("configure_output"), value_type=bool
                ),
                "imu_topic": "/imu/data",
                "mag_topic": "/imu/mag",
            }
        ],
    )

    return LaunchDescription(
        [
            port_arg,
            baud_arg,
            protocol_arg,
            frame_id_arg,
            configure_output_arg,
            node,
        ]
    )
