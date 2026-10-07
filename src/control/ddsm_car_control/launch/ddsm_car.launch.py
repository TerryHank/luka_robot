#!/usr/bin/env python3

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    # Legacy UDP/DDSM arguments are kept so existing bringup commands and includes
    # can keep passing them while the base implementation is now ZDT RS485.
    host_arg = DeclareLaunchArgument(
        "host",
        default_value="192.168.3.139",
        description="Legacy ESP32 STA IP address; ignored by the ZDT RS485 base",
    )
    command_port_arg = DeclareLaunchArgument(
        "command_port",
        default_value="9001",
        description="Legacy ESP32 UDP command port; ignored by the ZDT RS485 base",
    )
    odom_port_arg = DeclareLaunchArgument(
        "odom_port",
        default_value="9000",
        description="Legacy UDP odom listen port; ignored by the ZDT RS485 base",
    )

    serial_port_arg = DeclareLaunchArgument(
        "serial_port",
        default_value="/dev/serial/by-id/usb-FTDI_USB_Serial_Cable_UCBEA075-if00-port0",
        description="RS485 serial device for the ZDT Y42 motor bus",
    )
    protocol_arg = DeclareLaunchArgument(
        "protocol",
        default_value="free",
        description="ZDT communication protocol: free or modbus",
    )
    firmware_arg = DeclareLaunchArgument(
        "firmware",
        default_value="x",
        description="ZDT firmware command layout: x or emm",
    )
    free_ack_writes_arg = DeclareLaunchArgument(
        "free_ack_writes",
        default_value="true",
        description="Read free-protocol Receive acknowledgements after write commands",
    )
    feedback_enabled_arg = DeclareLaunchArgument(
        "feedback_enabled",
        default_value="false",
        description="Poll motor position feedback and publish wheel odometry",
    )
    read_speed_feedback_arg = DeclareLaunchArgument(
        "read_speed_feedback",
        default_value="false",
        description="Also poll realtime speed; off keeps RS485 bus lighter",
    )
    motor_ids_arg = DeclareLaunchArgument(
        "motor_ids",
        default_value="[1, 2, 3, 4]",
        description="Motor addresses in corner order: front-left, front-right, rear-left, rear-right",
    )
    motor_direction_1_arg = DeclareLaunchArgument(
        "motor_direction_1",
        default_value="1",
        description="Front-left motor sign",
    )
    motor_direction_2_arg = DeclareLaunchArgument(
        "motor_direction_2",
        default_value="-1",
        description="Front-right motor sign",
    )
    motor_direction_3_arg = DeclareLaunchArgument(
        "motor_direction_3",
        default_value="1",
        description="Rear-left motor sign",
    )
    motor_direction_4_arg = DeclareLaunchArgument(
        "motor_direction_4",
        default_value="-1",
        description="Rear-right motor sign",
    )
    wheel_diameter_arg = DeclareLaunchArgument(
        "wheel_diameter",
        default_value="0.1016",
        description="Mecanum wheel diameter in meters",
    )
    wheel_base_arg = DeclareLaunchArgument(
        "wheel_base",
        default_value="0.310",
        description="Front-rear wheel center distance in meters",
    )
    track_width_arg = DeclareLaunchArgument(
        "track_width",
        default_value="0.355",
        description="Left-right wheel center distance in meters",
    )
    motor_gear_ratio_arg = DeclareLaunchArgument(
        "motor_gear_ratio",
        default_value="1.0",
        description="Motor revolutions per wheel revolution",
    )
    cmd_freq_arg = DeclareLaunchArgument(
        "cmd_freq",
        default_value="20.0",
        description="Motor command update frequency in Hz",
    )
    feedback_freq_arg = DeclareLaunchArgument(
        "feedback_freq",
        default_value="20.0",
        description="Motor position polling frequency in Hz",
    )
    timeout_arg = DeclareLaunchArgument(
        "timeout",
        default_value="0.4",
        description="Stop after no cmd_vel for this many seconds",
    )
    max_linear_speed_arg = DeclareLaunchArgument(
        "max_linear_speed",
        default_value="0.3",
        description="Maximum planar speed in m/s",
    )
    max_angular_speed_arg = DeclareLaunchArgument(
        "max_angular_speed",
        default_value="1.0",
        description="Maximum angular speed in rad/s",
    )
    max_motor_rpm_arg = DeclareLaunchArgument(
        "max_motor_rpm",
        default_value="300.0",
        description="Maximum absolute motor rpm sent to each ZDT motor",
    )
    mecanum_forward_scale_arg = DeclareLaunchArgument(
        "mecanum_forward_scale",
        default_value="1.0",
        description="Scale applied to cmd_vel linear.x before mecanum mixing",
    )
    mecanum_lateral_scale_arg = DeclareLaunchArgument(
        "mecanum_lateral_scale",
        default_value="1.0",
        description="Scale applied to cmd_vel linear.y before mecanum mixing",
    )
    mecanum_lateral_direction_arg = DeclareLaunchArgument(
        "mecanum_lateral_direction",
        default_value="1",
        description="Hardware sign applied to cmd_vel linear.y before mecanum mixing",
    )
    mecanum_angular_scale_arg = DeclareLaunchArgument(
        "mecanum_angular_scale",
        default_value="1.0",
        description="Scale applied to cmd_vel angular.z before mecanum mixing",
    )
    acceleration_arg = DeclareLaunchArgument(
        "acceleration",
        default_value="0",
        description="ZDT speed-mode acceleration; 0 means auto: X=1000RPM/s, Emm=10",
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
    publish_tf_arg = DeclareLaunchArgument(
        "publish_tf",
        default_value="true",
        description="Publish raw odom->base_link TF from the bridge",
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
        default_value="false",
        description="Enable heading hold when cmd_vel angular.z is near zero",
    )
    heading_feedback_source_arg = DeclareLaunchArgument(
        "heading_feedback_source",
        default_value="imu",
        description="Heading PID feedback source: imu or odom",
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
        description="Minimum planar speed for heading hold",
    )
    heading_hold_angular_deadband_arg = DeclareLaunchArgument(
        "heading_hold_angular_deadband",
        default_value="0.02",
        description="Treat angular.z inside this band as straight driving",
    )
    heading_pid_max_feedback_age_arg = DeclareLaunchArgument(
        "heading_pid_max_feedback_age",
        default_value="0.5",
        description="Maximum IMU/odom feedback age used by heading PID in seconds",
    )

    zdt_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            PathJoinSubstitution(
                [
                    FindPackageShare("ddsm_car_control"),
                    "launch",
                    "zdt_y42_mecanum.launch.py",
                ]
            )
        ),
        launch_arguments={
            "serial_port": LaunchConfiguration("serial_port"),
            "protocol": LaunchConfiguration("protocol"),
            "firmware": LaunchConfiguration("firmware"),
            "free_ack_writes": LaunchConfiguration("free_ack_writes"),
            "feedback_enabled": LaunchConfiguration("feedback_enabled"),
            "read_speed_feedback": LaunchConfiguration("read_speed_feedback"),
            "motor_ids": LaunchConfiguration("motor_ids"),
            "motor_direction_1": LaunchConfiguration("motor_direction_1"),
            "motor_direction_2": LaunchConfiguration("motor_direction_2"),
            "motor_direction_3": LaunchConfiguration("motor_direction_3"),
            "motor_direction_4": LaunchConfiguration("motor_direction_4"),
            "wheel_diameter": LaunchConfiguration("wheel_diameter"),
            "wheel_base": LaunchConfiguration("wheel_base"),
            "track_width": LaunchConfiguration("track_width"),
            "motor_gear_ratio": LaunchConfiguration("motor_gear_ratio"),
            "cmd_freq": LaunchConfiguration("cmd_freq"),
            "feedback_freq": LaunchConfiguration("feedback_freq"),
            "timeout": LaunchConfiguration("timeout"),
            "max_linear_speed": LaunchConfiguration("max_linear_speed"),
            "max_angular_speed": LaunchConfiguration("max_angular_speed"),
            "max_motor_rpm": LaunchConfiguration("max_motor_rpm"),
            "mecanum_forward_scale": LaunchConfiguration("mecanum_forward_scale"),
            "mecanum_lateral_scale": LaunchConfiguration("mecanum_lateral_scale"),
            "mecanum_lateral_direction": LaunchConfiguration(
                "mecanum_lateral_direction"
            ),
            "mecanum_angular_scale": LaunchConfiguration("mecanum_angular_scale"),
            "acceleration": LaunchConfiguration("acceleration"),
            "odom_topic": LaunchConfiguration("odom_topic"),
            "odom_frame_id": LaunchConfiguration("odom_frame_id"),
            "base_frame_id": LaunchConfiguration("base_frame_id"),
            "publish_tf": LaunchConfiguration("publish_tf"),
            "encoder_log_period": LaunchConfiguration("encoder_log_period"),
            "imu_topic": LaunchConfiguration("imu_topic"),
            "heading_pid_enabled": LaunchConfiguration("heading_pid_enabled"),
            "heading_feedback_source": LaunchConfiguration("heading_feedback_source"),
            "heading_pid_kp": LaunchConfiguration("heading_pid_kp"),
            "heading_pid_ki": LaunchConfiguration("heading_pid_ki"),
            "heading_pid_kd": LaunchConfiguration("heading_pid_kd"),
            "heading_pid_max_wz": LaunchConfiguration("heading_pid_max_wz"),
            "heading_pid_max_integral": LaunchConfiguration("heading_pid_max_integral"),
            "heading_hold_min_vx": LaunchConfiguration("heading_hold_min_vx"),
            "heading_hold_angular_deadband": LaunchConfiguration(
                "heading_hold_angular_deadband"
            ),
            "heading_pid_max_feedback_age": LaunchConfiguration(
                "heading_pid_max_feedback_age"
            ),
        }.items(),
    )

    return LaunchDescription(
        [
            host_arg,
            command_port_arg,
            odom_port_arg,
            serial_port_arg,
            protocol_arg,
            firmware_arg,
            free_ack_writes_arg,
            feedback_enabled_arg,
            read_speed_feedback_arg,
            motor_ids_arg,
            motor_direction_1_arg,
            motor_direction_2_arg,
            motor_direction_3_arg,
            motor_direction_4_arg,
            wheel_diameter_arg,
            wheel_base_arg,
            track_width_arg,
            motor_gear_ratio_arg,
            cmd_freq_arg,
            feedback_freq_arg,
            timeout_arg,
            max_linear_speed_arg,
            max_angular_speed_arg,
            max_motor_rpm_arg,
            mecanum_forward_scale_arg,
            mecanum_lateral_scale_arg,
            mecanum_lateral_direction_arg,
            mecanum_angular_scale_arg,
            acceleration_arg,
            odom_topic_arg,
            odom_frame_arg,
            base_frame_arg,
            publish_tf_arg,
            encoder_log_period_arg,
            imu_topic_arg,
            heading_pid_enabled_arg,
            heading_feedback_source_arg,
            heading_pid_kp_arg,
            heading_pid_ki_arg,
            heading_pid_kd_arg,
            heading_pid_max_wz_arg,
            heading_pid_max_integral_arg,
            heading_hold_min_vx_arg,
            heading_hold_angular_deadband_arg,
            heading_pid_max_feedback_age_arg,
            zdt_launch,
        ]
    )
