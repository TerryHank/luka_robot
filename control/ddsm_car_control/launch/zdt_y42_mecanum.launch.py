#!/usr/bin/env python3

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    serial_port_arg = DeclareLaunchArgument(
        "serial_port",
        default_value="/dev/serial/by-id/usb-FTDI_USB_Serial_Cable_UCBEA075-if00-port0",
        description="RS485 adapter device for the ZDT Y42 motor bus",
    )
    baudrate_arg = DeclareLaunchArgument(
        "baudrate",
        default_value="115200",
        description="RS485 baudrate, default from the ZDT manual",
    )
    serial_timeout_arg = DeclareLaunchArgument(
        "serial_timeout",
        default_value="0.03",
        description="Serial read timeout in seconds",
    )
    protocol_arg = DeclareLaunchArgument(
        "protocol",
        default_value="free",
        description="Motor protocol: modbus or free",
    )
    firmware_arg = DeclareLaunchArgument(
        "firmware",
        default_value="x",
        description="Motor firmware command layout: emm or x",
    )
    modbus_ack_writes_arg = DeclareLaunchArgument(
        "modbus_ack_writes",
        default_value="true",
        description="Read and validate Modbus write responses",
    )
    free_ack_writes_arg = DeclareLaunchArgument(
        "free_ack_writes",
        default_value="true",
        description="Read free-protocol Receive acknowledgements after write commands",
    )
    motor_ids_arg = DeclareLaunchArgument(
        "motor_ids",
        default_value="[1, 2, 3, 4]",
        description="Motor addresses in corner order: FL, FR, RL, RR",
    )
    motor_direction_1_arg = DeclareLaunchArgument(
        "motor_direction_1",
        default_value="1",
        description="Front-left motor sign; flip to -1 if this wheel is reversed",
    )
    motor_direction_2_arg = DeclareLaunchArgument(
        "motor_direction_2",
        default_value="-1",
        description="Front-right motor sign; flip to 1 if this wheel is reversed",
    )
    motor_direction_3_arg = DeclareLaunchArgument(
        "motor_direction_3",
        default_value="1",
        description="Rear-left motor sign; flip to -1 if this wheel is reversed",
    )
    motor_direction_4_arg = DeclareLaunchArgument(
        "motor_direction_4",
        default_value="-1",
        description="Rear-right motor sign; flip to 1 if this wheel is reversed",
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
        description="Stop after no cmd_vel_nav for this many seconds",
    )
    manual_override_timeout_arg = DeclareLaunchArgument(
        "manual_override_timeout",
        default_value="0.5",
        description="Manual cmd_vel priority window in seconds",
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
    sync_motion_arg = DeclareLaunchArgument(
        "sync_motion",
        default_value="true",
        description="Cache each wheel command and use a broadcast sync trigger",
    )
    feedback_enabled_arg = DeclareLaunchArgument(
        "feedback_enabled",
        default_value="true",
        description="Poll motor position feedback and publish odometry",
    )
    read_speed_feedback_arg = DeclareLaunchArgument(
        "read_speed_feedback",
        default_value="false",
        description="Also poll realtime speed; off keeps RS485 bus lighter",
    )
    position_wrap_degrees_arg = DeclareLaunchArgument(
        "position_wrap_degrees",
        default_value="0.0",
        description="0 means cumulative motor position; use 360 if feedback wraps each turn",
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
        description="Publish odom->base_link TF from motor odometry",
    )
    encoder_log_period_arg = DeclareLaunchArgument(
        "encoder_log_period",
        default_value="5.0",
        description="Encoder snapshot publish/log period in seconds",
    )
    imu_topic_arg = DeclareLaunchArgument(
        "imu_topic",
        default_value="/imu/data",
        description="IMU topic used by heading hold PID feedback",
    )
    heading_pid_enabled_arg = DeclareLaunchArgument(
        "heading_pid_enabled",
        default_value="false",
        description="Enable heading hold while driving straight or strafing",
    )
    heading_feedback_source_arg = DeclareLaunchArgument(
        "heading_feedback_source",
        default_value="imu",
        description="Heading hold feedback source: imu or odom",
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

    bridge_node = Node(
        package="ddsm_car_control",
        executable="zdt_mecanum_rs485_bridge",
        name="zdt_mecanum_rs485_bridge",
        output="screen",
        parameters=[
            {
                "serial_port": LaunchConfiguration("serial_port"),
                "baudrate": ParameterValue(
                    LaunchConfiguration("baudrate"), value_type=int
                ),
                "serial_timeout": ParameterValue(
                    LaunchConfiguration("serial_timeout"), value_type=float
                ),
                "protocol": LaunchConfiguration("protocol"),
                "firmware": LaunchConfiguration("firmware"),
                "modbus_ack_writes": ParameterValue(
                    LaunchConfiguration("modbus_ack_writes"), value_type=bool
                ),
                "free_ack_writes": ParameterValue(
                    LaunchConfiguration("free_ack_writes"), value_type=bool
                ),
                "motor_ids": LaunchConfiguration("motor_ids"),
                "motor_direction_1": ParameterValue(
                    LaunchConfiguration("motor_direction_1"), value_type=int
                ),
                "motor_direction_2": ParameterValue(
                    LaunchConfiguration("motor_direction_2"), value_type=int
                ),
                "motor_direction_3": ParameterValue(
                    LaunchConfiguration("motor_direction_3"), value_type=int
                ),
                "motor_direction_4": ParameterValue(
                    LaunchConfiguration("motor_direction_4"), value_type=int
                ),
                "wheel_diameter": ParameterValue(
                    LaunchConfiguration("wheel_diameter"), value_type=float
                ),
                "wheel_base": ParameterValue(
                    LaunchConfiguration("wheel_base"), value_type=float
                ),
                "track_width": ParameterValue(
                    LaunchConfiguration("track_width"), value_type=float
                ),
                "motor_gear_ratio": ParameterValue(
                    LaunchConfiguration("motor_gear_ratio"), value_type=float
                ),
                "cmd_freq": ParameterValue(
                    LaunchConfiguration("cmd_freq"), value_type=float
                ),
                "feedback_freq": ParameterValue(
                    LaunchConfiguration("feedback_freq"), value_type=float
                ),
                "timeout": ParameterValue(
                    LaunchConfiguration("timeout"), value_type=float
                ),
                "manual_override_timeout": ParameterValue(
                    LaunchConfiguration("manual_override_timeout"), value_type=float
                ),
                "max_linear_speed": ParameterValue(
                    LaunchConfiguration("max_linear_speed"), value_type=float
                ),
                "max_angular_speed": ParameterValue(
                    LaunchConfiguration("max_angular_speed"), value_type=float
                ),
                "max_motor_rpm": ParameterValue(
                    LaunchConfiguration("max_motor_rpm"), value_type=float
                ),
                "mecanum_forward_scale": ParameterValue(
                    LaunchConfiguration("mecanum_forward_scale"), value_type=float
                ),
                "mecanum_lateral_scale": ParameterValue(
                    LaunchConfiguration("mecanum_lateral_scale"), value_type=float
                ),
                "mecanum_lateral_direction": ParameterValue(
                    LaunchConfiguration("mecanum_lateral_direction"), value_type=int
                ),
                "mecanum_angular_scale": ParameterValue(
                    LaunchConfiguration("mecanum_angular_scale"), value_type=float
                ),
                "acceleration": ParameterValue(
                    LaunchConfiguration("acceleration"), value_type=int
                ),
                "sync_motion": ParameterValue(
                    LaunchConfiguration("sync_motion"), value_type=bool
                ),
                "feedback_enabled": ParameterValue(
                    LaunchConfiguration("feedback_enabled"), value_type=bool
                ),
                "read_speed_feedback": ParameterValue(
                    LaunchConfiguration("read_speed_feedback"), value_type=bool
                ),
                "position_wrap_degrees": ParameterValue(
                    LaunchConfiguration("position_wrap_degrees"), value_type=float
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
            serial_port_arg,
            baudrate_arg,
            serial_timeout_arg,
            protocol_arg,
            firmware_arg,
            modbus_ack_writes_arg,
            free_ack_writes_arg,
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
            manual_override_timeout_arg,
            max_linear_speed_arg,
            max_angular_speed_arg,
            max_motor_rpm_arg,
            mecanum_forward_scale_arg,
            mecanum_lateral_scale_arg,
            mecanum_lateral_direction_arg,
            mecanum_angular_scale_arg,
            acceleration_arg,
            sync_motion_arg,
            feedback_enabled_arg,
            read_speed_feedback_arg,
            position_wrap_degrees_arg,
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
            bridge_node,
            encoder_logger_node,
        ]
    )
