#!/usr/bin/env python3

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


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
    timeout_arg = DeclareLaunchArgument(
        "timeout",
        default_value="0.4",
        description="Stop after no cmd_vel for this many seconds",
    )
    max_linear_speed_arg = DeclareLaunchArgument(
        "max_linear_speed",
        default_value="0.3",
        description="Maximum linear cmd_vel speed sent to the DDSM base in m/s; <=0 disables limiting",
    )
    odom_topic_arg = DeclareLaunchArgument(
        "odom_topic",
        default_value="odom",
        description="Odometry topic published by the bridge",
    )
    odom_frame_arg = DeclareLaunchArgument(
        "odom_frame_id",
        default_value="odom",
        description="Odometry frame id",
    )
    base_frame_arg = DeclareLaunchArgument(
        "base_frame_id",
        default_value="base_link",
        description="Robot base frame id",
    )
    encoder_log_period_arg = DeclareLaunchArgument(
        "encoder_log_period",
        default_value="5.0",
        description="Encoder snapshot publish/log period in seconds",
    )
    imu_topic_arg = DeclareLaunchArgument(
        "imu_topic",
        default_value="/imu/data",
        description="IMU topic used by heading PID feedback",
    )
    heading_pid_enabled_arg = DeclareLaunchArgument(
        "heading_pid_enabled",
        default_value="true",
        description="Enable heading hold when cmd_vel angular.z is near zero",
    )
    heading_feedback_source_arg = DeclareLaunchArgument(
        "heading_feedback_source",
        default_value="imu",
        description="Heading PID feedback source: imu or odom",
    )
    publish_tf_arg = DeclareLaunchArgument(
        "publish_tf",
        default_value="true",
        description="Publish raw odom->base_link TF from the bridge",
    )
    heading_pid_kp_arg = DeclareLaunchArgument(
        "heading_pid_kp",
        default_value="0.45",
        description="Heading hold proportional gain",
    )
    heading_pid_ki_arg = DeclareLaunchArgument(
        "heading_pid_ki",
        default_value="0.0",
        description="Heading hold integral gain",
    )
    heading_pid_kd_arg = DeclareLaunchArgument(
        "heading_pid_kd",
        default_value="0.0",
        description="Heading hold derivative gain",
    )
    heading_pid_max_wz_arg = DeclareLaunchArgument(
        "heading_pid_max_wz",
        default_value="0.08",
        description="Maximum heading correction angular velocity in rad/s",
    )
    heading_pid_max_integral_arg = DeclareLaunchArgument(
        "heading_pid_max_integral",
        default_value="0.05",
        description="Heading PID integral clamp",
    )
    heading_hold_min_vx_arg = DeclareLaunchArgument(
        "heading_hold_min_vx",
        default_value="0.03",
        description="Minimum absolute linear.x speed for heading hold",
    )
    heading_hold_angular_deadband_arg = DeclareLaunchArgument(
        "heading_hold_angular_deadband",
        default_value="0.02",
        description="Treat angular.z inside this band as straight driving",
    )
    heading_pid_max_odom_age_arg = DeclareLaunchArgument(
        "heading_pid_max_odom_age",
        default_value="0.5",
        description="Deprecated alias for heading_pid_max_feedback_age",
    )
    heading_pid_max_feedback_age_arg = DeclareLaunchArgument(
        "heading_pid_max_feedback_age",
        default_value="0.5",
        description="Maximum IMU/odom feedback age used by heading PID in seconds",
    )

    bridge_node = Node(
        package="ddsm_car_control",
        executable="udp_cmd_vel_bridge",
        name="udp_cmd_vel_bridge",
        output="screen",
        parameters=[
            {
                "host": LaunchConfiguration("host"),
                "command_port": ParameterValue(
                    LaunchConfiguration("command_port"), value_type=int
                ),
                "odom_port": ParameterValue(
                    LaunchConfiguration("odom_port"), value_type=int
                ),
                "cmd_freq": ParameterValue(
                    LaunchConfiguration("cmd_freq"), value_type=float
                ),
                "timeout": ParameterValue(
                    LaunchConfiguration("timeout"), value_type=float
                ),
                "max_linear_speed": ParameterValue(
                    LaunchConfiguration("max_linear_speed"), value_type=float
                ),
                "odom_frame_id": LaunchConfiguration("odom_frame_id"),
                "base_frame_id": LaunchConfiguration("base_frame_id"),
                "publish_tf": ParameterValue(
                    LaunchConfiguration("publish_tf"), value_type=bool
                ),
                "imu_topic": LaunchConfiguration("imu_topic"),
                "heading_pid_enabled": ParameterValue(
                    LaunchConfiguration("heading_pid_enabled"), value_type=bool
                ),
                "heading_feedback_source": LaunchConfiguration(
                    "heading_feedback_source"
                ),
                "heading_pid_kp": ParameterValue(
                    LaunchConfiguration("heading_pid_kp"), value_type=float
                ),
                "heading_pid_ki": ParameterValue(
                    LaunchConfiguration("heading_pid_ki"), value_type=float
                ),
                "heading_pid_kd": ParameterValue(
                    LaunchConfiguration("heading_pid_kd"), value_type=float
                ),
                "heading_pid_max_wz": ParameterValue(
                    LaunchConfiguration("heading_pid_max_wz"), value_type=float
                ),
                "heading_pid_max_integral": ParameterValue(
                    LaunchConfiguration("heading_pid_max_integral"), value_type=float
                ),
                "heading_hold_min_vx": ParameterValue(
                    LaunchConfiguration("heading_hold_min_vx"), value_type=float
                ),
                "heading_hold_angular_deadband": ParameterValue(
                    LaunchConfiguration("heading_hold_angular_deadband"),
                    value_type=float,
                ),
                "heading_pid_max_odom_age": ParameterValue(
                    LaunchConfiguration("heading_pid_max_odom_age"), value_type=float
                ),
                "heading_pid_max_feedback_age": ParameterValue(
                    LaunchConfiguration("heading_pid_max_feedback_age"),
                    value_type=float,
                ),
            }
        ],
        remappings=[
            ("odom", LaunchConfiguration("odom_topic")),
        ],
    )

    encoder_logger_node = Node(
        package="ddsm_car_control",
        executable="encoder_logger",
        name="encoder_logger",
        output="screen",
        parameters=[
            {
                "input_topic": "ddsm/data_chain",
                "output_topic": "ddsm/encoder_snapshot",
                "period": ParameterValue(
                    LaunchConfiguration("encoder_log_period"), value_type=float
                ),
            }
        ],
    )

    return LaunchDescription(
        [
            host_arg,
            command_port_arg,
            odom_port_arg,
            cmd_freq_arg,
            timeout_arg,
            max_linear_speed_arg,
            odom_topic_arg,
            odom_frame_arg,
            base_frame_arg,
            encoder_log_period_arg,
            imu_topic_arg,
            heading_pid_enabled_arg,
            heading_feedback_source_arg,
            publish_tf_arg,
            heading_pid_kp_arg,
            heading_pid_ki_arg,
            heading_pid_kd_arg,
            heading_pid_max_wz_arg,
            heading_pid_max_integral_arg,
            heading_hold_min_vx_arg,
            heading_hold_angular_deadband_arg,
            heading_pid_max_odom_age_arg,
            heading_pid_max_feedback_age_arg,
            bridge_node,
            encoder_logger_node,
        ]
    )
