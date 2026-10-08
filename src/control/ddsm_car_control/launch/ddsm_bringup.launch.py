#!/usr/bin/env python3

from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    EmitEvent,
    GroupAction,
    IncludeLaunchDescription,
    LogInfo,
    RegisterEventHandler,
    TimerAction,
)
from launch.conditions import IfCondition
from launch.events import matches_action
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import (
    EnvironmentVariable,
    LaunchConfiguration,
    PathJoinSubstitution,
    PythonExpression,
)
from launch_ros.actions import LifecycleNode, Node, SetParameter, SetRemap
from launch_ros.event_handlers import OnStateTransition
from launch_ros.events.lifecycle import ChangeState
from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare
from lifecycle_msgs.msg import Transition


def enabled_for_mode_expression(flag_name, modes):
    mode_list = ", ".join([f"'{mode}'" for mode in modes])
    return [
        "'",
        LaunchConfiguration(flag_name),
        "' == 'true' or ('",
        LaunchConfiguration(flag_name),
        "' == 'auto' and '",
        LaunchConfiguration("mode"),
        "' in [",
        mode_list,
        "])",
    ]


def enabled_for_mode(flag_name, modes):
    return IfCondition(PythonExpression(enabled_for_mode_expression(flag_name, modes)))


def low_cpu_nav_enabled(modes):
    return IfCondition(
        PythonExpression(
            [
                "(",
                *enabled_for_mode_expression("enable_nav", modes),
                ") and '",
                LaunchConfiguration("low_cpu_nav"),
                "' in ['1', 'true', 'True']",
            ]
        )
    )


def low_cpu_nav_disabled(modes):
    return IfCondition(
        PythonExpression(
            [
                "(",
                *enabled_for_mode_expression("enable_nav", modes),
                ") and '",
                LaunchConfiguration("low_cpu_nav"),
                "' not in ['1', 'true', 'True']",
            ]
        )
    )


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
        default_value="50.0",
        description="UDP command send frequency in Hz",
    )
    feedback_enabled_arg = DeclareLaunchArgument(
        "feedback_enabled",
        default_value="true",
        description="Read ZDT motor position feedback and publish wheel odometry",
    )
    read_speed_feedback_arg = DeclareLaunchArgument(
        "read_speed_feedback",
        default_value="false",
        description="Also read ZDT realtime speed feedback; position feedback is enough for odometry",
    )
    feedback_freq_arg = DeclareLaunchArgument(
        "feedback_freq",
        default_value="30.0",
        description="ZDT motor position feedback polling frequency in Hz",
    )
    max_linear_speed_arg = DeclareLaunchArgument(
        "max_linear_speed",
        default_value="1.8",
        description="Maximum linear speed sent to the DDSM base in m/s",
    )
    max_angular_speed_arg = DeclareLaunchArgument(
        "max_angular_speed",
        default_value="9.0",
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
        description="ZDT speed-mode acceleration; 0 means auto",
    )
    timeout_arg = DeclareLaunchArgument(
        "timeout",
        default_value="0.4",
        description="Stop after no cmd_vel for this many seconds",
    )
    mode_arg = DeclareLaunchArgument(
        "mode",
        default_value="bringup",
        description=(
            "Function mode: bringup, slam, nav, auto_nav, slam_nav, explore, or custom"
        ),
    )
    enable_slam_arg = DeclareLaunchArgument(
        "enable_slam",
        default_value="auto",
        description="Start slam_toolbox when true, or when mode is slam if auto",
    )
    enable_nav_arg = DeclareLaunchArgument(
        "enable_nav",
        default_value="auto",
        description=(
            "Start Nav2 when true, or when mode is nav/auto_nav/slam_nav/explore if auto"
        ),
    )
    low_cpu_nav_arg = DeclareLaunchArgument(
        "low_cpu_nav",
        default_value="true",
        description=(
            "Use a reduced Nav2 process set for low-power IPCs in nav/auto_nav modes"
        ),
    )
    enable_auto_localizer_arg = DeclareLaunchArgument(
        "enable_auto_localizer",
        default_value="auto",
        description=(
            "Start AMCL auto relocalizer when true, or when mode is auto_nav if auto"
        ),
    )
    enable_patrol_manager_arg = DeclareLaunchArgument(
        "enable_patrol_manager",
        default_value="auto",
        description=(
            "Start DDSM patrol manager when true, or when mode is nav/auto_nav if auto"
        ),
    )
    enable_waterplus_bridge_arg = DeclareLaunchArgument(
        "enable_waterplus_bridge",
        default_value="auto",
        description=(
            "Start WaterPlus-compatible Foxglove waypoint bridge when true, "
            "or when mode is nav/auto_nav if auto"
        ),
    )
    enable_semantic_map_arg = DeclareLaunchArgument(
        "enable_semantic_map",
        default_value="auto",
        description=(
            "Start named hotel areas and destination services when true, "
            "or when mode is nav/auto_nav if auto"
        ),
    )
    enable_named_navigation_arg = DeclareLaunchArgument(
        "enable_named_navigation",
        default_value="auto",
        description=(
            "Start named-destination navigation when true, "
            "or when mode is nav/auto_nav if auto"
        ),
    )
    enable_mission_control_arg = DeclareLaunchArgument(
        "enable_mission_control",
        default_value="auto",
        description="Enable unified hotel mission pause/resume/cancel control",
    )
    enable_multifloor_manager_arg = DeclareLaunchArgument(
        "enable_multifloor_manager",
        default_value="false",
        description="Enable semi-automatic multi-floor hotel mission manager",
    )
    enable_elevator_adapter_arg = DeclareLaunchArgument(
        "enable_elevator_adapter",
        default_value="auto",
        description="Enable the replaceable elevator protocol adapter",
    )
    enable_elevator_entry_controller_arg = DeclareLaunchArgument(
        "enable_elevator_entry_controller",
        default_value="false",
        description="Enable the first-version automatic elevator entry controller",
    )
    enable_llm_agent_arg = DeclareLaunchArgument(
        "enable_llm_agent",
        # The router is managed by nav-llm-agent.service so it can load the
        # protected cloud credential and restart independently.  Starting a
        # second copy here causes duplicate answers and a local-only fallback.
        default_value="false",
        description="Deprecated: router is started by nav-llm-agent.service",
    )
    llm_waypoints_file_arg = DeclareLaunchArgument(
        "llm_waypoints_file",
        default_value=PathJoinSubstitution(
            [FindPackageShare("nav_llm_agent"), "config", "waypoints.yaml"]
        ),
        description="Waypoint catalog exposed to the LLM",
    )
    llm_capabilities_file_arg = DeclareLaunchArgument(
        "llm_capabilities_file",
        default_value=PathJoinSubstitution(
            [FindPackageShare("nav_llm_agent"), "config", "capabilities.yaml"]
        ),
        description="Robot capability and workflow registry",
    )
    llm_url_arg = DeclareLaunchArgument(
        "llm_url",
        default_value="http://127.0.0.1:8080",
        description="OpenAI-compatible local LLM server URL",
    )
    llm_model_arg = DeclareLaunchArgument(
        "llm_model",
        default_value="qwen2.5-1.5b",
        description="Model identifier sent to the local LLM server",
    )
    elevator_entry_params_file_arg = DeclareLaunchArgument(
        "elevator_entry_params_file",
        default_value=PathJoinSubstitution(
            [
                FindPackageShare("ddsm_car_control"),
                "config",
                "elevator_entry_v1.yaml",
            ]
        ),
        description="Parameter file for automatic elevator entry controller",
    )
    elevator_backend_arg = DeclareLaunchArgument(
        "elevator_backend",
        default_value="manual",
        description="Elevator adapter backend; manual is used until vendor protocol arrives",
    )
    multifloor_current_floor_id_arg = DeclareLaunchArgument(
        "multifloor_current_floor_id",
        default_value="",
        description="Override multi-floor current floor based on the loaded map",
    )
    enable_waterplus_goal_pose_alias_arg = DeclareLaunchArgument(
        "enable_waterplus_goal_pose_alias",
        default_value="true",
        description=(
            "If true, Foxglove /goal_pose clicks append WaterPlus patrol waypoints"
        ),
    )
    enable_explore_arg = DeclareLaunchArgument(
        "enable_explore",
        default_value="auto",
        description="Start explore_lite when true, or when mode is explore if auto",
    )
    enable_home_manager_arg = DeclareLaunchArgument(
        "enable_home_manager",
        default_value="auto",
        description=(
            "Start DDSM Home Manager when true, or when mode is nav/auto_nav/slam_nav if auto"
        ),
    )
    enable_final_approach_arg = DeclareLaunchArgument(
        "enable_final_approach",
        default_value="auto",
        description=(
            "Start staged final approach helper when true, or when mode is nav/auto_nav/slam_nav if auto"
        ),
    )
    enable_lateral_escape_guard_arg = DeclareLaunchArgument(
        "enable_lateral_escape_guard",
        default_value="auto",
        description=(
            "Runtime navigation motion-mode adapter. It switches between Omni and "
            "forward-facing motion; timed lateral escape remains disabled"
        ),
    )
    navigation_motion_mode_arg = DeclareLaunchArgument(
        "navigation_motion_mode",
        default_value=EnvironmentVariable(
            "NAVIGATION_MOTION_MODE", default_value="omni"
        ),
        choices=["omni", "forward_facing"],
        description="Navigation chassis mode: omni or adaptive forward-facing mecanum",
    )
    enable_base_driver_arg = DeclareLaunchArgument(
        "enable_base_driver",
        default_value="true",
        description="Start DDSM base driver and wheel odometry bridge",
    )
    enable_imu_arg = DeclareLaunchArgument(
        "enable_imu",
        default_value="true",
        description="Start HWT906 IMU driver",
    )
    imu_port_arg = DeclareLaunchArgument(
        "imu_port",
        default_value="/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0",
        description="HWT906 IMU serial port",
    )
    imu_baud_arg = DeclareLaunchArgument(
        "imu_baud",
        default_value="921600",
        description="HWT906 IMU baud rate",
    )
    imu_protocol_arg = DeclareLaunchArgument(
        "imu_protocol",
        default_value="normal",
        description="WIT IMU protocol: normal or modbus",
    )
    imu_configure_output_arg = DeclareLaunchArgument(
        "imu_configure_output",
        default_value="true",
        description="Send WIT standard-protocol output-enable command on startup",
    )
    imu_heading_mode_arg = DeclareLaunchArgument(
        "imu_heading_mode",
        default_value="relative",
        choices=["relative", "absolute"],
        description=(
            "HWT906 heading mode for EKF: relative zeros yaw at launch; "
            "absolute uses the sensor's magnetic/AHRS heading directly"
        ),
    )
    heading_pid_enabled_arg = DeclareLaunchArgument(
        "heading_pid_enabled",
        default_value="false",
        description="Enable IMU-yaw heading hold when cmd_vel angular.z is near zero",
    )
    heading_feedback_source_arg = DeclareLaunchArgument(
        "heading_feedback_source",
        default_value="imu",
        description="Heading hold feedback source passed to the base driver: imu or odom",
    )
    heading_pid_kp_arg = DeclareLaunchArgument(
        "heading_pid_kp",
        default_value="0.45",
        description="Heading hold proportional gain",
    )
    heading_pid_max_wz_arg = DeclareLaunchArgument(
        "heading_pid_max_wz",
        default_value="0.08",
        description="Maximum heading correction angular velocity in rad/s",
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
    enable_teleop_arg = DeclareLaunchArgument(
        "enable_teleop",
        default_value="false",
        description="Start teleop_twist_keyboard node (requires interactive terminal)",
    )
    teleop_speed_arg = DeclareLaunchArgument(
        "teleop_speed",
        default_value="0.5",
        description="Teleop default linear speed in m/s",
    )
    teleop_turn_arg = DeclareLaunchArgument(
        "teleop_turn",
        default_value="1.0",
        description="Teleop default angular speed in rad/s",
    )
    enable_ekf_arg = DeclareLaunchArgument(
        "enable_ekf",
        default_value="true",
        description="Start robot_localization EKF",
    )
    enable_lidar_arg = DeclareLaunchArgument(
        "enable_lidar",
        default_value="true",
        description="Enable laser scan processing",
    )
    start_lidar_driver_arg = DeclareLaunchArgument(
        "start_lidar_driver",
        default_value=EnvironmentVariable("START_LIDAR_DRIVER", default_value="true"),
        description="Start the RPLIDAR driver inside this launch",
    )
    enable_dual_lidar_arg = DeclareLaunchArgument(
        "enable_dual_lidar",
        default_value=EnvironmentVariable("ENABLE_DUAL_LIDAR", default_value="true"),
        choices=["true", "false"],
        description="Start the low S3 lidar and fuse it with the navigation scan",
    )
    low_lidar_ip_arg = DeclareLaunchArgument(
        "low_lidar_ip",
        default_value=EnvironmentVariable("LOW_LIDAR_IP", default_value="192.168.11.2"),
        description="Low S3 Ethernet adapter address",
    )
    low_lidar_port_arg = DeclareLaunchArgument(
        "low_lidar_port",
        default_value=EnvironmentVariable("LOW_LIDAR_PORT", default_value="8089"),
        description="Low S3 Ethernet adapter UDP port",
    )
    low_lidar_x_arg = DeclareLaunchArgument(
        "low_lidar_x", default_value="0.346",
        description="Low lidar x offset relative to the primary lidar frame",
    )
    low_lidar_y_arg = DeclareLaunchArgument(
        "low_lidar_y", default_value="0.005",
        description="Low lidar y offset relative to the primary lidar frame",
    )
    low_lidar_z_arg = DeclareLaunchArgument(
        "low_lidar_z", default_value="0.10",
        description="Low lidar height relative to base_link for visualization",
    )
    low_lidar_yaw_arg = DeclareLaunchArgument(
        "low_lidar_yaw", default_value="1.56975",
        description="Low lidar yaw correction in radians",
    )
    low_lidar_inverted_arg = DeclareLaunchArgument(
        "low_lidar_inverted", default_value="true", choices=["true", "false"],
        description="Set true only when the low lidar is mounted upside down",
    )
    low_lidar_keep_min_deg_arg = DeclareLaunchArgument(
        "low_lidar_keep_min_deg", default_value="-180.0",
        description="Start of the unblocked low-lidar sector in sensor degrees",
    )
    low_lidar_keep_max_deg_arg = DeclareLaunchArgument(
        "low_lidar_keep_max_deg", default_value="0.0",
        description="End of the unblocked low-lidar sector in sensor degrees; wrapping is supported",
    )
    enable_depth_camera_arg = DeclareLaunchArgument(
        "enable_depth_camera",
        default_value=EnvironmentVariable(
            "ENABLE_DEPTH_CAMERA", default_value="auto"
        ),
        description=(
            "Start the Orbbec depth camera in navigation modes when auto"
        ),
    )
    enable_colored_point_cloud_arg = DeclareLaunchArgument(
        "enable_colored_point_cloud",
        default_value=EnvironmentVariable(
            "ENABLE_COLORED_POINT_CLOUD", default_value="false"
        ),
        choices=["true", "false"],
        description="Align RGB to depth and publish /camera/depth_registered/points",
    )
    enable_depth_obstacle_fusion_arg = DeclareLaunchArgument(
        "enable_depth_obstacle_fusion",
        default_value=EnvironmentVariable(
            "ENABLE_DEPTH_OBSTACLE_FUSION", default_value="true"
        ),
        choices=["true", "false"],
        description="Fuse depth-camera obstacles into the navigation scan",
    )
    enable_semantic_mapping_arg = DeclareLaunchArgument(
        "enable_semantic_mapping",
        default_value=EnvironmentVariable(
            "ENABLE_SEMANTIC_MAPPING", default_value="auto"
        ),
        description=(
            "Detect and record doors, fixed furniture and room candidates "
            "in navigation and mapping modes when auto"
        ),
    )
    semantic_floor_id_arg = DeclareLaunchArgument(
        "semantic_floor_id",
        default_value=EnvironmentVariable(
            "SEMANTIC_FLOOR_ID", default_value="floor_1"
        ),
        description="Floor id written into automatic semantic detections",
    )
    semantic_output_file_arg = DeclareLaunchArgument(
        "semantic_output_file",
        default_value=EnvironmentVariable(
            "SEMANTIC_OUTPUT_FILE",
            default_value=(
                "/home/sunrise/luka_ws/src/common/config/semantic_auto/"
                "floor_1/detections.yaml"
            ),
        ),
        description="Separate YAML file for automatic semantic detections",
    )
    camera_x_arg = DeclareLaunchArgument(
        "camera_x",
        default_value="0.20",
        description="Camera x offset from base_link in meters",
    )
    camera_y_arg = DeclareLaunchArgument(
        "camera_y",
        default_value="0.0",
        description="Camera y offset from base_link in meters",
    )
    camera_z_arg = DeclareLaunchArgument(
        "camera_z",
        default_value="0.32",
        description="Camera z offset from base_link in meters",
    )
    enable_laser_tf_arg = DeclareLaunchArgument(
        "enable_laser_tf",
        default_value="true",
        description="Publish base_link to laser static transform",
    )
    laser_x_arg = DeclareLaunchArgument(
        "laser_x",
        default_value="-0.065",
        description="Laser x offset from base_link in meters",
    )
    laser_y_arg = DeclareLaunchArgument(
        "laser_y",
        default_value="0.0",
        description="Laser y offset from base_link in meters",
    )
    laser_z_arg = DeclareLaunchArgument(
        "laser_z",
        default_value="0.42",
        description="Laser z offset from base_link in meters",
    )
    laser_yaw_arg = DeclareLaunchArgument(
        "laser_yaw",
        default_value="0.0",
        description="Laser yaw offset from base_link in radians",
    )
    lidar_scan_frequency_arg = DeclareLaunchArgument(
        "lidar_scan_frequency",
        default_value="12.0",
        description="RPLIDAR scan frequency in Hz",
    )
    lidar_topic_name_arg = DeclareLaunchArgument(
        "lidar_topic_name",
        default_value="/scan",
        description="RPLIDAR LaserScan output topic",
    )
    enable_scan_deskew_arg = DeclareLaunchArgument(
        "enable_scan_deskew",
        default_value=EnvironmentVariable(
            "ENABLE_SCAN_DESKEW", default_value="true"
        ),
        description="Deskew RPLIDAR scans with filtered wheel/IMU odometry",
    )
    scan_publish_frequency_arg = DeclareLaunchArgument(
        "scan_publish_frequency",
        default_value="0.0",
        description=(
            "If > 0, publish RPLIDAR on /scan_raw and throttle it back to /scan "
            "at this frequency in Hz"
        ),
    )
    map_arg = DeclareLaunchArgument(
        "map",
        default_value="/home/sunrise/luka_data/maps/ddsm_map.yaml",
        description="Full path to the saved map YAML file for Nav2",
    )
    home_pose_file_arg = DeclareLaunchArgument(
        "home_pose_file",
        default_value="/home/sunrise/luka_ws/src/common/config/home_pose.yaml",
        description="Writable Home pose YAML file used by ddsm_home_manager",
    )
    home_map_file_arg = DeclareLaunchArgument(
        "home_map_file",
        default_value=LaunchConfiguration("map"),
        description="Map YAML used to validate saved Home poses",
    )
    auto_localizer_last_pose_file_arg = DeclareLaunchArgument(
        "auto_localizer_last_pose_file",
        default_value="/home/sunrise/luka_ws/src/common/config/last_amcl_pose.yaml",
        description="Writable AMCL last pose YAML file used by auto_nav mode",
    )
    auto_localizer_enable_rotation_arg = DeclareLaunchArgument(
        "auto_localizer_enable_rotation",
        default_value="true",
        description="Allow auto_nav to rotate slowly while AMCL globally localizes",
    )
    auto_localizer_max_rotation_speed_arg = DeclareLaunchArgument(
        "auto_localizer_max_rotation_speed",
        default_value="0.22",
        description="Maximum auto localization rotation speed in rad/s",
    )
    auto_localizer_rotation_clearance_arg = DeclareLaunchArgument(
        "auto_localizer_rotation_clearance",
        default_value="0.45",
        description="Minimum laser range required before auto localization rotates",
    )
    auto_localizer_enable_escape_arg = DeclareLaunchArgument(
        "auto_localizer_enable_escape",
        default_value="true",
        description="Allow short local moves when rotation clearance is blocked",
    )
    auto_localizer_escape_speed_arg = DeclareLaunchArgument(
        "auto_localizer_escape_speed",
        default_value="0.08",
        description="Linear speed for auto localization local escape in m/s",
    )
    auto_localizer_escape_lateral_direction_arg = DeclareLaunchArgument(
        "auto_localizer_escape_lateral_direction",
        default_value="1.0",
        description="Lateral direction multiplier for auto localization local escape",
    )
    auto_localizer_escape_duration_arg = DeclareLaunchArgument(
        "auto_localizer_escape_duration",
        default_value="1.5",
        description="Seconds per auto localization local escape attempt",
    )
    auto_localizer_escape_max_attempts_arg = DeclareLaunchArgument(
        "auto_localizer_escape_max_attempts",
        default_value="3",
        description="Maximum local escape attempts during auto localization",
    )
    auto_localizer_warm_start_timeout_arg = DeclareLaunchArgument(
        "auto_localizer_warm_start_timeout",
        default_value="20.0",
        description="Seconds to try saved AMCL pose before global localization",
    )
    auto_localizer_global_timeout_arg = DeclareLaunchArgument(
        "auto_localizer_global_timeout",
        default_value="180.0",
        description="Seconds to rotate and wait for global AMCL convergence",
    )
    auto_localizer_xy_std_threshold_arg = DeclareLaunchArgument(
        "auto_localizer_xy_std_threshold",
        default_value="0.20",
        description="AMCL x/y covariance standard deviation threshold for readiness",
    )
    auto_localizer_yaw_std_threshold_arg = DeclareLaunchArgument(
        "auto_localizer_yaw_std_threshold",
        default_value="0.25",
        description="AMCL yaw covariance standard deviation threshold for readiness",
    )
    patrol_route_file_arg = DeclareLaunchArgument(
        "patrol_route_file",
        default_value="/home/sunrise/luka_ws/src/common/config/patrol_route.yaml",
        description="Writable patrol route YAML used by ddsm_patrol_manager",
    )
    mission_state_file_arg = DeclareLaunchArgument(
        "mission_state_file",
        default_value="/home/sunrise/luka_ws/src/common/config/mission_state.yaml",
        description="Persistent mission control recovery-state YAML",
    )
    mission_zero_velocity_seconds_arg = DeclareLaunchArgument(
        "mission_zero_velocity_seconds",
        default_value="1.0",
        description="Seconds to publish zero velocity on pause/cancel",
    )
    mission_zero_velocity_hz_arg = DeclareLaunchArgument(
        "mission_zero_velocity_hz",
        default_value="10.0",
        description="Zero velocity publish rate on pause/cancel",
    )
    multifloor_building_config_file_arg = DeclareLaunchArgument(
        "multifloor_building_config_file",
        default_value="/home/sunrise/luka_ws/src/common/config/multifloor_building.yaml",
        description="YAML file describing floors, maps, elevators, and destinations",
    )
    multifloor_state_file_arg = DeclareLaunchArgument(
        "multifloor_state_file",
        default_value="/home/sunrise/luka_ws/src/common/config/floor_mission_state.yaml",
        description="Persistent semi-automatic multi-floor mission state YAML",
    )
    semantic_map_manifest_arg = DeclareLaunchArgument(
        "semantic_map_manifest",
        default_value=PathJoinSubstitution(
            [FindPackageShare("hotel_semantic_map"), "config", "map_manifest.yaml"]
        ),
        description="Versioned hotel semantic-map manifest YAML",
    )
    named_navigation_action_arg = DeclareLaunchArgument(
        "named_navigation_action",
        default_value="/hotel/navigate_to_destination",
        description="ROS 2 action used for named hotel destination navigation",
    )
    named_navigation_require_localization_arg = DeclareLaunchArgument(
        "named_navigation_require_localization",
        default_value="true",
        description="Wait for auto-localizer or stable AMCL covariance before moving",
    )
    waterplus_waypoints_file_arg = DeclareLaunchArgument(
        "waterplus_waypoints_file",
        default_value="/home/sunrise/luka_ws/src/common/config/waypoints.xml",
        description="Writable WaterPlus XML waypoint file used by Foxglove waypoint bridge",
    )
    waterplus_default_waypoint_type_arg = DeclareLaunchArgument(
        "waterplus_default_waypoint_type",
        default_value="stop",
        description=(
            "Waypoint type assigned to Foxglove WaterPlus points; use delivery_stop "
            "to route them through final approach"
        ),
    )
    waterplus_default_final_approach_arg = DeclareLaunchArgument(
        "waterplus_default_final_approach",
        default_value="false",
        description="If true, WaterPlus-added waypoints use staged final approach",
    )
    waterplus_goal_pose_topic_arg = DeclareLaunchArgument(
        "waterplus_goal_pose_topic",
        default_value="/goal_pose",
        description=(
            "PoseStamped topic used as a Foxglove 2D Nav Goal alias for WaterPlus points"
        ),
    )
    nav2_goal_pose_topic_arg = DeclareLaunchArgument(
        "nav2_goal_pose_topic",
        default_value="/nav_goal_pose",
        description="PoseStamped topic for direct Nav2 single-goal commands",
    )
    final_approach_goal_topic_arg = DeclareLaunchArgument(
        "final_approach_goal_topic",
        default_value="/final_approach/goal_pose",
        description="Internal PoseStamped topic used by patrol manager to trigger final approach",
    )
    nav_controller_cmd_vel_topic_arg = DeclareLaunchArgument(
        "nav_controller_cmd_vel_topic",
        default_value="/cmd_vel_nav_raw",
        description=(
            "Internal Nav2 cmd_vel topic consumed by the runtime motion-mode adapter."
        ),
    )
    lateral_escape_direction_sign_arg = DeclareLaunchArgument(
        "lateral_escape_direction_sign",
        default_value="1.0",
        description="Set to -1.0 if the lateral escape hardware direction is inverted",
    )
    patrol_require_localization_ready_arg = DeclareLaunchArgument(
        "patrol_require_localization_ready",
        default_value="true",
        description="Wait for /localization/ready before patrol starts moving",
    )
    nav_params_file_arg = DeclareLaunchArgument(
        "nav_params_file",
        default_value=PathJoinSubstitution(
            [FindPackageShare("ddsm_car_control"), "config", "nav2_params.yaml"]
        ),
        description="Full path to the Nav2 parameter file",
    )
    amcl_transform_tolerance_arg = DeclareLaunchArgument(
        "amcl_transform_tolerance",
        default_value=EnvironmentVariable(
            "AMCL_TRANSFORM_TOLERANCE", default_value="0.2"
        ),
        description="AMCL map-to-odom transform future-dating tolerance in seconds",
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
    explore_params_file_arg = DeclareLaunchArgument(
        "explore_params_file",
        default_value=PathJoinSubstitution(
            [FindPackageShare("ddsm_car_control"), "config", "explore_lite.yaml"]
        ),
        description="Full path to explore_lite parameter file",
    )
    slam_map_update_interval_arg = DeclareLaunchArgument(
        "slam_map_update_interval",
        default_value="0.15",
        description="slam_toolbox map_update_interval in seconds for mapping mode",
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
        default_value="12.0",
        description="Public /map republish frequency in Hz for visualization",
    )
    lifecycle_bond_timeout_arg = DeclareLaunchArgument(
        "lifecycle_bond_timeout",
        default_value="180.0",
        description="Nav2 lifecycle manager bond timeout in seconds for low-power IPCs",
    )
    nav_start_delay_arg = DeclareLaunchArgument(
        "nav_start_delay",
        default_value="45.0",
        description=(
            "Delay Nav2 navigation servers in saved-map modes so AMCL can activate "
            "first on low-power IPCs"
        ),
    )
    nav_node_batch_delay_arg = DeclareLaunchArgument(
        "nav_node_batch_delay",
        default_value="12.0",
        description="Delay between Nav2 navigation process batches in seconds",
    )
    mission_start_delay_arg = DeclareLaunchArgument(
        "mission_start_delay",
        default_value="150.0",
        description=(
            "Delay optional hotel mission services until Nav2 startup load has settled"
        ),
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
            "serial_port": LaunchConfiguration("serial_port"),
            "protocol": LaunchConfiguration("protocol"),
            "firmware": LaunchConfiguration("firmware"),
            "free_ack_writes": LaunchConfiguration("free_ack_writes"),
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
            "feedback_enabled": LaunchConfiguration("feedback_enabled"),
            "read_speed_feedback": LaunchConfiguration("read_speed_feedback"),
            "feedback_freq": LaunchConfiguration("feedback_freq"),
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
            "timeout": LaunchConfiguration("timeout"),
            "ekf_params_file": LaunchConfiguration("ekf_params_file"),
            "enable_base_driver": LaunchConfiguration("enable_base_driver"),
            "enable_imu": LaunchConfiguration("enable_imu"),
            "imu_port": LaunchConfiguration("imu_port"),
            "imu_baud": LaunchConfiguration("imu_baud"),
            "imu_protocol": LaunchConfiguration("imu_protocol"),
            "imu_configure_output": LaunchConfiguration("imu_configure_output"),
            "imu_heading_mode": LaunchConfiguration("imu_heading_mode"),
            "heading_pid_enabled": LaunchConfiguration("heading_pid_enabled"),
            "heading_feedback_source": LaunchConfiguration("heading_feedback_source"),
            "heading_pid_kp": LaunchConfiguration("heading_pid_kp"),
            "heading_pid_max_wz": LaunchConfiguration("heading_pid_max_wz"),
            "heading_hold_min_vx": LaunchConfiguration("heading_hold_min_vx"),
            "heading_hold_angular_deadband": LaunchConfiguration(
                "heading_hold_angular_deadband"
            ),
            "enable_ekf": LaunchConfiguration("enable_ekf"),
            "enable_lidar": LaunchConfiguration("enable_lidar"),
            "start_lidar_driver": LaunchConfiguration("start_lidar_driver"),
            "enable_scan_deskew": LaunchConfiguration("enable_scan_deskew"),
            "enable_laser_tf": LaunchConfiguration("enable_laser_tf"),
            "laser_x": LaunchConfiguration("laser_x"),
            "laser_y": LaunchConfiguration("laser_y"),
            "laser_z": LaunchConfiguration("laser_z"),
            "laser_yaw": LaunchConfiguration("laser_yaw"),
            "lidar_scan_frequency": LaunchConfiguration("lidar_scan_frequency"),
            "lidar_topic_name": PythonExpression(
                [
                    "'/scan_raw' if ('",
                    LaunchConfiguration("enable_scan_deskew"),
                    "' == 'true' or float('",
                    LaunchConfiguration("scan_publish_frequency"),
                    "') > 0.0) else '/scan'",
                ]
            ),
            "scan_deskew_input_topic": "/scan_raw",
            "scan_deskew_output_topic": PythonExpression(
                [
                    "'/scan_deskewed' if float('",
                    LaunchConfiguration("scan_publish_frequency"),
                    "') > 0.0 else '/scan'",
                ]
            ),
            "scan_deskew_odom_topic": "/odometry/filtered",
        }.items(),
    )

    low_lidar_proxy = Node(
        package="ddsm_car_control",
        executable="low_lidar_udp_proxy",
        name="low_lidar_udp_proxy",
        output="screen",
        respawn=True,
        respawn_delay=2.0,
        arguments=[
            "--interface", "eth0",
            "--source-ip", "192.168.11.11",
            "--target-ip", LaunchConfiguration("low_lidar_ip"),
            "--target-port", LaunchConfiguration("low_lidar_port"),
            "--listen-port", "18089",
        ],
        condition=IfCondition(LaunchConfiguration("enable_dual_lidar")),
    )

    low_lidar_driver = Node(
        package="rplidar_ros",
        executable="rplidar_node",
        name="rplidar_low_node",
        output="screen",
        respawn=True,
        respawn_delay=3.0,
        parameters=[
            {
                "channel_type": "udp",
                "udp_ip": "127.0.0.1",
                "udp_port": 18089,
                "frame_id": "laser_low",
                "inverted": ParameterValue(
                    LaunchConfiguration("low_lidar_inverted"), value_type=bool
                ),
                "angle_compensate": True,
                "scan_mode": "Sensitivity",
                "scan_frequency": 10.0,
                "topic_name": "/scan_low_raw",
            }
        ],
        condition=IfCondition(LaunchConfiguration("enable_dual_lidar")),
    )

    low_lidar_tf = Node(
        package="tf2_ros",
        executable="static_transform_publisher",
        name="low_lidar_static_tf",
        output="screen",
        arguments=[
            "--x", PythonExpression(
                [
                    "str(float('", LaunchConfiguration("laser_x"),
                    "') + float('", LaunchConfiguration("low_lidar_x"), "'))",
                ]
            ),
            "--y", LaunchConfiguration("low_lidar_y"),
            "--z", LaunchConfiguration("low_lidar_z"),
            "--roll", "0.0", "--pitch", "0.0",
            "--yaw", PythonExpression(
                [
                    "str(float('", LaunchConfiguration("laser_yaw"),
                    "') + float('", LaunchConfiguration("low_lidar_yaw"), "'))",
                ]
            ),
            "--frame-id", "base_link",
            "--child-frame-id", "laser_low",
        ],
        condition=IfCondition(LaunchConfiguration("enable_dual_lidar")),
    )

    dual_laser_fusion = Node(
        package="ddsm_car_control",
        executable="dual_laser_fusion",
        name="dual_laser_fusion",
        output="screen",
        respawn=True,
        respawn_delay=2.0,
        parameters=[
            {
                "primary_topic": "/scan",
                "secondary_topic": "/scan_low_raw",
                "secondary_filtered_topic": "/scan_low_filtered",
                "output_topic": "/scan_obstacle_fused",
                "secondary_x": ParameterValue(
                    LaunchConfiguration("low_lidar_x"), value_type=float
                ),
                "secondary_y": ParameterValue(
                    LaunchConfiguration("low_lidar_y"), value_type=float
                ),
                "secondary_yaw": ParameterValue(
                    LaunchConfiguration("low_lidar_yaw"), value_type=float
                ),
                "secondary_keep_min_deg": ParameterValue(
                    LaunchConfiguration("low_lidar_keep_min_deg"), value_type=float
                ),
                "secondary_keep_max_deg": ParameterValue(
                    LaunchConfiguration("low_lidar_keep_max_deg"), value_type=float
                ),
                "secondary_self_filter_enabled": True,
                "secondary_self_filter_min_x": -0.30,
                "secondary_self_filter_max_x": 0.30,
                "secondary_self_filter_min_y": -0.21,
                "secondary_self_filter_max_y": 0.21,
                "secondary_timeout": 0.25,
                "secondary_sync_tolerance": 0.15,
                "fused_publish_rate": 5.0,
            }
        ],
        condition=IfCondition(LaunchConfiguration("enable_dual_lidar")),
    )

    depth_camera = Node(
        package="orbbec_camera",
        executable="orbbec_camera_node",
        namespace="camera",
        name="ob_camera_node",
        output="screen",
        respawn=True,
        respawn_delay=2.0,
        parameters=[
            {
                "camera_name": "camera",
                "enable_point_cloud": False,
                "enable_colored_point_cloud": ParameterValue(
                    LaunchConfiguration("enable_colored_point_cloud"),
                    value_type=bool,
                ),
                "cloud_frame_id": "camera_depth_optical_frame",
                "enable_color": ParameterValue(
                    PythonExpression(
                        [
                            "'",
                            LaunchConfiguration("enable_colored_point_cloud"),
                            "' == 'true' or (",
                            *enabled_for_mode_expression(
                                "enable_semantic_mapping",
                                ["nav", "auto_nav", "slam", "slam_nav", "explore"],
                            ),
                            ")",
                        ]
                    ),
                    value_type=bool,
                ),
                "color_width": 640,
                "color_height": 480,
                "color_fps": 30,
                "color_format": "MJPG",
                "depth_registration": ParameterValue(
                    LaunchConfiguration("enable_colored_point_cloud"),
                    value_type=bool,
                ),
                "enable_ir": False,
                "depth_width": ParameterValue(
                    PythonExpression(
                        [
                            "640 if '",
                            LaunchConfiguration("enable_colored_point_cloud"),
                            "' == 'true' else 320",
                        ]
                    ),
                    value_type=int,
                ),
                "depth_height": ParameterValue(
                    PythonExpression(
                        [
                            "480 if '",
                            LaunchConfiguration("enable_colored_point_cloud"),
                            "' == 'true' else 240",
                        ]
                    ),
                    value_type=int,
                ),
                "depth_fps": 30,
                "depth_format": "Y11",
                "publish_tf": False,
            }
        ],
        condition=enabled_for_mode(
            "enable_depth_camera", ["nav", "auto_nav", "slam", "slam_nav", "explore"]
        ),
    )

    depth_camera_tf = Node(
        package="tf2_ros",
        executable="static_transform_publisher",
        name="depth_camera_static_tf",
        output="screen",
        arguments=[
            "--x",
            LaunchConfiguration("camera_x"),
            "--y",
            LaunchConfiguration("camera_y"),
            "--z",
            LaunchConfiguration("camera_z"),
            "--roll",
            "0.0",
            "--pitch",
            "0.0",
            "--yaw",
            "0.0",
            "--frame-id",
            "base_link",
            "--child-frame-id",
            "camera_link",
        ],
        condition=enabled_for_mode(
            "enable_depth_camera", ["nav", "auto_nav", "slam", "slam_nav", "explore"]
        ),
    )

    depth_camera_optical_tf = Node(
        package="tf2_ros",
        executable="static_transform_publisher",
        name="depth_camera_optical_static_tf",
        output="screen",
        arguments=[
            "--x",
            "0.0",
            "--y",
            "0.0",
            "--z",
            "0.0",
            "--roll",
            "-1.5707963267948966",
            "--pitch",
            "0.0",
            "--yaw",
            "-1.5707963267948966",
            "--frame-id",
            "camera_link",
            "--child-frame-id",
            "camera_depth_optical_frame",
        ],
        condition=enabled_for_mode(
            "enable_depth_camera", ["nav", "auto_nav", "slam", "slam_nav", "explore"]
        ),
    )

    depth_camera_color_optical_tf = Node(
        package="tf2_ros",
        executable="static_transform_publisher",
        name="depth_camera_color_optical_static_tf",
        output="screen",
        arguments=[
            "--x", "0.0", "--y", "0.0", "--z", "0.0",
            "--roll", "-1.5707963267948966",
            "--pitch", "0.0",
            "--yaw", "-1.5707963267948966",
            "--frame-id", "camera_link",
            "--child-frame-id", "camera_color_optical_frame",
        ],
        condition=IfCondition(
            PythonExpression(
                [
                    "'",
                    LaunchConfiguration("enable_colored_point_cloud"),
                    "' == 'true' or (",
                    *enabled_for_mode_expression(
                        "enable_semantic_mapping",
                        ["nav", "auto_nav", "slam", "slam_nav", "explore"],
                    ),
                    ")",
                ]
            )
        ),
    )

    colored_point_cloud_relay = Node(
        package="ddsm_car_control",
        executable="colored_point_cloud_relay",
        name="colored_point_cloud_relay",
        output="screen",
        respawn=True,
        respawn_delay=2.0,
        condition=IfCondition(LaunchConfiguration("enable_colored_point_cloud")),
    )

    depth_obstacle_monitor = Node(
        package="ddsm_car_control",
        executable="depth_obstacle_monitor",
        name="depth_obstacle_monitor",
        output="screen",
        respawn=True,
        respawn_delay=2.0,
        parameters=[
            {
                "depth_image_topic": "/camera/depth/image_raw",
                "camera_info_topic": "/camera/depth/camera_info",
                "scan_input_topic": "/scan",
                "fused_scan_topic": "/scan_obstacle_fused",
                "depth_scan_topic": "/depth_camera/confirmed_obstacle_scan",
                "processing_rate": 8.0,
                "depth_unit_scale": 0.001,
                "base_frame": "base_link",
                "memory_frame": "odom",
                "obstacle_memory_duration": 2.5,
                "obstacle_memory_resolution": 0.05,
                "min_x": 0.20,
                "max_x": 2.5,
                "max_abs_y": 1.0,
                "min_z": 0.05,
                "max_z": 0.45,
                "corridor_half_width": 0.30,
                "stop_distance": 0.55,
                "sample_stride": 8,
                "depth_timeout": 0.5,
                "confirmation_distance_tolerance": 0.20,
            }
        ],
        condition=IfCondition(
            PythonExpression(
                [
                    "'", LaunchConfiguration("enable_depth_obstacle_fusion"),
                    "' == 'true' and '", LaunchConfiguration("enable_dual_lidar"),
                    "' != 'true' and (",
                    *enabled_for_mode_expression(
                        "enable_depth_camera",
                        ["nav", "auto_nav", "slam", "slam_nav", "explore"],
                    ),
                    ")",
                ]
            )
        ),
    )

    semantic_mapping_recorder = Node(
        package="ddsm_car_control",
        executable="semantic_mapping_recorder",
        name="semantic_mapping_recorder",
        output="screen",
        respawn=True,
        respawn_delay=5.0,
        parameters=[
            {
                "floor_id": LaunchConfiguration("semantic_floor_id"),
                "output_file": LaunchConfiguration("semantic_output_file"),
                "enable_door_model": False,
                "door_model": "/home/sunrise/luka_data/ml_models/common/semantic/doorway_seg_yolo26n.onnx",
                "furniture_model": "/home/sunrise/luka_data/ml_models/common/semantic/yolo11n_rk3588_fp16.rknn",
                "furniture_fallback_model": "/home/sunrise/luka_data/ml_models/common/semantic/yolo11n.onnx",
                "rknn_runtime_library": "/home/sunrise/luka_ws/src/common/vendor/rknn-downloads/librknnrt.so",
                "rknn_input_size": 320,
                "furniture_cfg": "/home/sunrise/luka_data/ml_models/common/semantic/yolov4-tiny.cfg",
                "furniture_weights": "/home/sunrise/luka_data/ml_models/common/semantic/yolov4-tiny.weights",
                "coco_names": "/home/sunrise/luka_data/ml_models/common/semantic/coco.names",
                "inference_rate": 0.2,
                "preview_rate": 0.5,
                "publish_annotated_image": True,
                "use_compressed_color": True,
                "confidence_threshold": 0.65,
                "doorway_confidence_threshold": 0.78,
                "door_confidence_threshold": 0.72,
                "window_confidence_threshold": 0.70,
                "confirm_observations": 15,
                "confirm_min_span": 5.0,
                "structural_confirm_observations": 12,
                "structural_confirm_min_span": 5.0,
                "structural_max_position_stddev": 0.25,
                "merge_distance": 1.0,
                "generate_object_waypoints": ParameterValue(
                    EnvironmentVariable("SEMANTIC_GENERATE_OBJECT_WAYPOINTS", default_value="false"),
                    value_type=bool,
                ),
            }
        ],
        condition=enabled_for_mode(
            "enable_semantic_mapping",
            ["nav", "auto_nav", "slam", "slam_nav", "explore"],
        ),
    )

    scan_throttler = Node(
        package="ddsm_car_control",
        executable="scan_throttler",
        name="scan_throttler",
        output="screen",
        parameters=[
            {
                "input_topic": PythonExpression(
                    [
                        "'/scan_deskewed' if '",
                        LaunchConfiguration("enable_scan_deskew"),
                        "' == 'true' else '/scan_raw'",
                    ]
                ),
                "output_topic": "/scan",
                "publish_frequency": LaunchConfiguration("scan_publish_frequency"),
            }
        ],
        condition=IfCondition(
            PythonExpression(
                [
                    "float('",
                    LaunchConfiguration("scan_publish_frequency"),
                    "') > 0.0",
                ]
            )
        ),
    )

    teleop_keyboard = Node(
        package="teleop_twist_keyboard",
        executable="teleop_twist_keyboard",
        name="teleop_twist_keyboard",
        output="screen",
        parameters=[
            {
                "speed": LaunchConfiguration("teleop_speed"),
                "turn": LaunchConfiguration("teleop_turn"),
            }
        ],
        condition=IfCondition(
            PythonExpression(
                [
                    "'",
                    LaunchConfiguration("enable_teleop"),
                    "' == 'true'",
                ]
            )
        ),
    )

    slam_toolbox_node = LifecycleNode(
        package="slam_toolbox",
        executable="async_slam_toolbox_node",
        name="slam_toolbox",
        output="screen",
        namespace="",
        parameters=[
            LaunchConfiguration("slam_params_file"),
            {
                "use_lifecycle_manager": False,
                "use_sim_time": False,
                "map_update_interval": ParameterValue(
                    LaunchConfiguration("slam_map_update_interval"),
                    value_type=float,
                ),
            },
        ],
    )

    slam_toolbox_configure = EmitEvent(
        event=ChangeState(
            lifecycle_node_matcher=matches_action(slam_toolbox_node),
            transition_id=Transition.TRANSITION_CONFIGURE,
        )
    )

    slam_toolbox_activate = RegisterEventHandler(
        OnStateTransition(
            target_lifecycle_node=slam_toolbox_node,
            start_state="configuring",
            goal_state="inactive",
            entities=[
                LogInfo(msg="[DDSM] Activating slam_toolbox."),
                EmitEvent(
                    event=ChangeState(
                        lifecycle_node_matcher=matches_action(slam_toolbox_node),
                        transition_id=Transition.TRANSITION_ACTIVATE,
                    )
                ),
            ],
        )
    )

    slam_toolbox = GroupAction(
        [
            SetRemap(src="/map", dst="/slam_map"),
            slam_toolbox_node,
            slam_toolbox_configure,
            slam_toolbox_activate,
        ],
        condition=enabled_for_mode("enable_slam", ["slam", "explore"]),
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
        condition=enabled_for_mode("enable_slam", ["slam", "explore"]),
    )

    nav2_localization = GroupAction(
        [
            SetParameter(
                "bond_timeout",
                ParameterValue(
                    LaunchConfiguration("lifecycle_bond_timeout"),
                    value_type=float,
                ),
            ),
            Node(
                package="nav2_map_server",
                executable="map_server",
                name="map_server",
                output="screen",
                respawn=LaunchConfiguration("use_respawn"),
                respawn_delay=2.0,
                parameters=[
                    LaunchConfiguration("nav_params_file"),
                    {"yaml_filename": LaunchConfiguration("map")},
                ],
                arguments=["--ros-args", "--log-level", LaunchConfiguration("log_level")],
                remappings=[("/tf", "tf"), ("/tf_static", "tf_static")],
            ),
            Node(
                package="nav2_amcl",
                executable="amcl",
                name="amcl",
                output="screen",
                respawn=LaunchConfiguration("use_respawn"),
                respawn_delay=2.0,
                parameters=[
                    LaunchConfiguration("nav_params_file"),
                    {
                        "transform_tolerance": ParameterValue(
                            LaunchConfiguration("amcl_transform_tolerance"),
                            value_type=float,
                        )
                    },
                ],
                arguments=["--ros-args", "--log-level", LaunchConfiguration("log_level")],
                remappings=[("/tf", "tf"), ("/tf_static", "tf_static")],
            ),
            # Let both lifecycle services settle before the manager sends transitions.
            TimerAction(
                period=2.0,
                actions=[
                    Node(
                        package="nav2_lifecycle_manager",
                        executable="lifecycle_manager",
                        name="lifecycle_manager_localization",
                        output="screen",
                        arguments=[
                            "--ros-args",
                            "--log-level",
                            LaunchConfiguration("log_level"),
                        ],
                        parameters=[
                            {
                                "autostart": ParameterValue(
                                    LaunchConfiguration("autostart"),
                                    value_type=bool,
                                )
                            },
                            {"node_names": ["map_server", "amcl"]},
                        ],
                    )
                ],
            ),
        ],
        condition=enabled_for_mode("enable_nav", ["nav", "auto_nav"]),
    )

    auto_localizer = Node(
        package="ddsm_car_control",
        executable="ddsm_auto_localizer",
        name="ddsm_auto_localizer",
        output="screen",
        parameters=[
            {
                "map_file": LaunchConfiguration("map"),
                "last_pose_file": LaunchConfiguration("auto_localizer_last_pose_file"),
                "map_frame": "map",
                "initial_pose_topic": "/initialpose",
                "amcl_pose_topic": "/amcl_pose",
                "scan_topic": "/scan",
                "cmd_vel_topic": "/cmd_vel_nav",
                "enable_rotation": ParameterValue(
                    LaunchConfiguration("auto_localizer_enable_rotation"),
                    value_type=bool,
                ),
                "max_rotation_speed": ParameterValue(
                    LaunchConfiguration("auto_localizer_max_rotation_speed"),
                    value_type=float,
                ),
                "rotation_clearance": ParameterValue(
                    LaunchConfiguration("auto_localizer_rotation_clearance"),
                    value_type=float,
                ),
                "enable_escape": ParameterValue(
                    LaunchConfiguration("auto_localizer_enable_escape"),
                    value_type=bool,
                ),
                "escape_speed": ParameterValue(
                    LaunchConfiguration("auto_localizer_escape_speed"),
                    value_type=float,
                ),
                "escape_lateral_direction": ParameterValue(
                    LaunchConfiguration("auto_localizer_escape_lateral_direction"),
                    value_type=float,
                ),
                "escape_duration": ParameterValue(
                    LaunchConfiguration("auto_localizer_escape_duration"),
                    value_type=float,
                ),
                "escape_max_attempts": ParameterValue(
                    LaunchConfiguration("auto_localizer_escape_max_attempts"),
                    value_type=int,
                ),
                "warm_start_timeout": ParameterValue(
                    LaunchConfiguration("auto_localizer_warm_start_timeout"),
                    value_type=float,
                ),
                "global_localization_timeout": ParameterValue(
                    LaunchConfiguration("auto_localizer_global_timeout"),
                    value_type=float,
                ),
                "xy_std_threshold": ParameterValue(
                    LaunchConfiguration("auto_localizer_xy_std_threshold"),
                    value_type=float,
                ),
                "yaw_std_threshold": ParameterValue(
                    LaunchConfiguration("auto_localizer_yaw_std_threshold"),
                    value_type=float,
                ),
            }
        ],
        condition=enabled_for_mode("enable_auto_localizer", ["auto_nav"]),
    )

    lateral_escape_guard = Node(
        package="ddsm_car_control",
        executable="ddsm_lateral_escape_guard",
        name="lateral_escape_guard",
        output="screen",
        parameters=[
            {
                "cmd_vel_in_topic": LaunchConfiguration("nav_controller_cmd_vel_topic"),
                "cmd_vel_out_topic": "/cmd_vel_nav",
                "scan_topic": "/scan_obstacle_fused",
                "camera_depth_image_topic": "/camera/depth/image_raw",
                "camera_info_topic": "/camera/depth/camera_info",
                "depth_distance_topic": "/depth_camera/nearest_obstacle_distance",
                "path_topic": "/plan",
                "base_frame": "base_link",
                "status_topic": "/lateral_escape/status",
                "initial_motion_mode": LaunchConfiguration(
                    "navigation_motion_mode"
                ),
                "active_escape_enabled": False,
                "heading_align_kp": 1.4,
                "heading_align_max_wz": 0.9,
                "heading_normal_lateral_ratio": 0.10,
                "heading_normal_lateral_max": 0.05,
                "heading_obstacle_lateral_ratio": 0.85,
                "heading_obstacle_lateral_max": 0.22,
                "heading_obstacle_release_distance": 1.20,
                "heading_linear_accel_limit": 0.90,
                "heading_lateral_accel_limit": 0.80,
                "heading_angular_accel_limit": 2.40,
                "control_frequency": 15.0,
                "min_forward_cmd": 0.10,
                "forward_dominance_ratio": 1.0,
                "path_timeout": 3.0,
                "terminal_no_escape_distance": 0.60,
                    "front_trigger_distance": 0.58,
                "front_clear_distance": 0.85,
                        "min_side_clearance": 0.46,
                    "min_side_advantage": 0.38,
                        "escape_side_stop_distance": 0.55,
                    "narrow_passage_side_limit": 0.82,
                        "narrow_passage_front_stop_distance": 0.38,
                        "escape_cooldown_duration": 2.0,
                "escape_lateral_speed": 0.30,
                "escape_forward_speed": 0.0,
                "lateral_direction_sign": LaunchConfiguration(
                    "lateral_escape_direction_sign"
                ),
                "min_escape_duration": 0.50,
                "max_escape_duration": 1.6,
                "camera_processing_frequency": 8.0,
                "camera_pixel_step": 8,
                "camera_min_height": 0.04,
                "camera_max_height": 1.20,
                "camera_front_half_width": 0.24,
                "camera_min_points": 3,
                "camera_confirmation_frames": 2,
                "camera_obstacle_persistence": 0.25,
            }
        ],
        condition=enabled_for_mode("enable_lateral_escape_guard", ["nav", "auto_nav"]),
    )

    nav2_navigation = GroupAction(
        [
            SetParameter(
                "bond_timeout",
                ParameterValue(
                    LaunchConfiguration("lifecycle_bond_timeout"),
                    value_type=float,
                ),
            ),
            Node(
                package="nav2_controller",
                executable="controller_server",
                output="screen",
                respawn=LaunchConfiguration("use_respawn"),
                respawn_delay=2.0,
                parameters=[LaunchConfiguration("nav_params_file")],
                arguments=["--ros-args", "--log-level", LaunchConfiguration("log_level")],
                remappings=[
                    ("/tf", "tf"),
                    ("/tf_static", "tf_static"),
                    ("cmd_vel", LaunchConfiguration("nav_controller_cmd_vel_topic")),
                ],
            ),
            Node(
                package="nav2_smoother",
                executable="smoother_server",
                name="smoother_server",
                output="screen",
                respawn=LaunchConfiguration("use_respawn"),
                respawn_delay=2.0,
                parameters=[LaunchConfiguration("nav_params_file")],
                arguments=["--ros-args", "--log-level", LaunchConfiguration("log_level")],
                remappings=[
                    ("/tf", "tf"),
                    ("/tf_static", "tf_static"),
                ],
            ),
            Node(
                package="nav2_planner",
                executable="planner_server",
                name="planner_server",
                output="screen",
                respawn=LaunchConfiguration("use_respawn"),
                respawn_delay=2.0,
                parameters=[LaunchConfiguration("nav_params_file")],
                arguments=["--ros-args", "--log-level", LaunchConfiguration("log_level")],
                remappings=[
                    ("/tf", "tf"),
                    ("/tf_static", "tf_static"),
                ],
            ),
            TimerAction(
                period=PythonExpression(
                    ["0.5 * ", LaunchConfiguration("nav_node_batch_delay")]
                ),
                actions=[
                    Node(
                        package="nav2_lifecycle_manager",
                        executable="lifecycle_manager",
                        name="lifecycle_manager_navigation_core",
                        output="screen",
                        arguments=["--ros-args", "--log-level", LaunchConfiguration("log_level")],
                        parameters=[
                            {"autostart": True},
                            {
                                "node_names": [
                                    "controller_server",
                                    "smoother_server",
                                    "planner_server",
                                ]
                            },
                        ],
                    ),
                ],
            ),
            TimerAction(
                period=LaunchConfiguration("nav_node_batch_delay"),
                actions=[
                    Node(
                        package="nav2_route",
                        executable="route_server",
                        name="route_server",
                        output="screen",
                        respawn=LaunchConfiguration("use_respawn"),
                        respawn_delay=2.0,
                        parameters=[LaunchConfiguration("nav_params_file")],
                        arguments=["--ros-args", "--log-level", LaunchConfiguration("log_level")],
                        remappings=[
                            ("/tf", "tf"),
                            ("/tf_static", "tf_static"),
                        ],
                    ),
                    Node(
                        package="nav2_behaviors",
                        executable="behavior_server",
                        name="behavior_server",
                        output="screen",
                        respawn=LaunchConfiguration("use_respawn"),
                        respawn_delay=2.0,
                        parameters=[LaunchConfiguration("nav_params_file")],
                        arguments=["--ros-args", "--log-level", LaunchConfiguration("log_level")],
                        remappings=[
                            ("/tf", "tf"),
                            ("/tf_static", "tf_static"),
                            ("cmd_vel", LaunchConfiguration("nav_controller_cmd_vel_topic")),
                        ],
                    ),
                    Node(
                        package="nav2_bt_navigator",
                        executable="bt_navigator",
                        name="bt_navigator",
                        output="screen",
                        respawn=LaunchConfiguration("use_respawn"),
                        respawn_delay=2.0,
                        parameters=[LaunchConfiguration("nav_params_file")],
                        arguments=["--ros-args", "--log-level", LaunchConfiguration("log_level")],
                        remappings=[
                            ("/tf", "tf"),
                            ("/tf_static", "tf_static"),
                            ("goal_pose", LaunchConfiguration("nav2_goal_pose_topic")),
                        ],
                    ),
                    Node(
                        package="nav2_waypoint_follower",
                        executable="waypoint_follower",
                        name="waypoint_follower",
                        output="screen",
                        respawn=LaunchConfiguration("use_respawn"),
                        respawn_delay=2.0,
                        parameters=[LaunchConfiguration("nav_params_file")],
                        arguments=["--ros-args", "--log-level", LaunchConfiguration("log_level")],
                        remappings=[
                            ("/tf", "tf"),
                            ("/tf_static", "tf_static"),
                        ],
                    ),
                ],
            ),
            TimerAction(
                period=PythonExpression(
                    ["1.5 * ", LaunchConfiguration("nav_node_batch_delay")]
                ),
                actions=[
                    Node(
                        package="nav2_lifecycle_manager",
                        executable="lifecycle_manager",
                        name="lifecycle_manager_navigation_behavior",
                        output="screen",
                        arguments=["--ros-args", "--log-level", LaunchConfiguration("log_level")],
                        parameters=[
                            {"autostart": True},
                            {
                                "node_names": [
                                    "route_server",
                                    "behavior_server",
                                    "bt_navigator",
                                    "waypoint_follower",
                                ]
                            },
                        ],
                    ),
                ],
            ),
            TimerAction(
                period=PythonExpression(
                    ["2.0 * ", LaunchConfiguration("nav_node_batch_delay")]
                ),
                actions=[
                    Node(
                        package="nav2_velocity_smoother",
                        executable="velocity_smoother",
                        name="velocity_smoother",
                        output="screen",
                        respawn=LaunchConfiguration("use_respawn"),
                        respawn_delay=2.0,
                        parameters=[LaunchConfiguration("nav_params_file")],
                        arguments=["--ros-args", "--log-level", LaunchConfiguration("log_level")],
                        remappings=[
                            ("/tf", "tf"),
                            ("/tf_static", "tf_static"),
                            ("cmd_vel", LaunchConfiguration("nav_controller_cmd_vel_topic")),
                        ],
                    ),
                    Node(
                        package="nav2_collision_monitor",
                        executable="collision_monitor",
                        name="collision_monitor",
                        output="screen",
                        respawn=LaunchConfiguration("use_respawn"),
                        respawn_delay=2.0,
                        parameters=[LaunchConfiguration("nav_params_file")],
                        arguments=["--ros-args", "--log-level", LaunchConfiguration("log_level")],
                        remappings=[
                            ("/tf", "tf"),
                            ("/tf_static", "tf_static"),
                        ],
                    ),
                ],
            ),
            TimerAction(
                period=PythonExpression(
                    ["2.5 * ", LaunchConfiguration("nav_node_batch_delay")]
                ),
                actions=[
                    Node(
                        package="nav2_lifecycle_manager",
                        executable="lifecycle_manager",
                        name="lifecycle_manager_navigation_safety",
                        output="screen",
                        arguments=["--ros-args", "--log-level", LaunchConfiguration("log_level")],
                        parameters=[
                            {"autostart": True},
                            {
                                "node_names": [
                                    "velocity_smoother",
                                    "collision_monitor",
                                ]
                            },
                        ],
                    ),
                ],
            ),
        ],
        condition=low_cpu_nav_disabled(["nav", "auto_nav"]),
    )

    nav2_navigation_lite = GroupAction(
        [
            SetParameter(
                "bond_timeout",
                ParameterValue(
                    LaunchConfiguration("lifecycle_bond_timeout"),
                    value_type=float,
                ),
            ),
            Node(
                package="nav2_controller",
                executable="controller_server",
                output="screen",
                respawn=LaunchConfiguration("use_respawn"),
                respawn_delay=2.0,
                parameters=[LaunchConfiguration("nav_params_file")],
                arguments=["--ros-args", "--log-level", LaunchConfiguration("log_level")],
                remappings=[
                    ("/tf", "tf"),
                    ("/tf_static", "tf_static"),
                    ("cmd_vel", LaunchConfiguration("nav_controller_cmd_vel_topic")),
                ],
            ),
            Node(
                package="nav2_smoother",
                executable="smoother_server",
                name="smoother_server",
                output="screen",
                respawn=LaunchConfiguration("use_respawn"),
                respawn_delay=2.0,
                parameters=[LaunchConfiguration("nav_params_file")],
                arguments=["--ros-args", "--log-level", LaunchConfiguration("log_level")],
                remappings=[
                    ("/tf", "tf"),
                    ("/tf_static", "tf_static"),
                ],
            ),
            Node(
                package="nav2_planner",
                executable="planner_server",
                name="planner_server",
                output="screen",
                respawn=LaunchConfiguration("use_respawn"),
                respawn_delay=2.0,
                parameters=[LaunchConfiguration("nav_params_file")],
                arguments=["--ros-args", "--log-level", LaunchConfiguration("log_level")],
                remappings=[
                    ("/tf", "tf"),
                    ("/tf_static", "tf_static"),
                ],
            ),
            TimerAction(
                period=PythonExpression(
                    ["0.5 * ", LaunchConfiguration("nav_node_batch_delay")]
                ),
                actions=[
                    Node(
                        package="nav2_lifecycle_manager",
                        executable="lifecycle_manager",
                        name="lifecycle_manager_navigation_core",
                        output="screen",
                        arguments=["--ros-args", "--log-level", LaunchConfiguration("log_level")],
                        parameters=[
                            {"autostart": True},
                            {
                                "node_names": [
                                    "controller_server",
                                    "smoother_server",
                                    "planner_server",
                                ]
                            },
                        ],
                    ),
                ],
            ),
            TimerAction(
                period=LaunchConfiguration("nav_node_batch_delay"),
                actions=[
                    Node(
                        package="nav2_behaviors",
                        executable="behavior_server",
                        name="behavior_server",
                        output="screen",
                        respawn=LaunchConfiguration("use_respawn"),
                        respawn_delay=2.0,
                        parameters=[LaunchConfiguration("nav_params_file")],
                        arguments=["--ros-args", "--log-level", LaunchConfiguration("log_level")],
                        remappings=[
                            ("/tf", "tf"),
                            ("/tf_static", "tf_static"),
                            ("cmd_vel", LaunchConfiguration("nav_controller_cmd_vel_topic")),
                        ],
                    ),
                    Node(
                        package="nav2_bt_navigator",
                        executable="bt_navigator",
                        name="bt_navigator",
                        output="screen",
                        respawn=LaunchConfiguration("use_respawn"),
                        respawn_delay=2.0,
                        parameters=[LaunchConfiguration("nav_params_file")],
                        arguments=["--ros-args", "--log-level", LaunchConfiguration("log_level")],
                        remappings=[
                            ("/tf", "tf"),
                            ("/tf_static", "tf_static"),
                            ("goal_pose", LaunchConfiguration("nav2_goal_pose_topic")),
                        ],
                    ),
                ],
            ),
            TimerAction(
                period=PythonExpression(
                    ["1.5 * ", LaunchConfiguration("nav_node_batch_delay")]
                ),
                actions=[
                    Node(
                        package="nav2_lifecycle_manager",
                        executable="lifecycle_manager",
                        name="lifecycle_manager_navigation_behavior",
                        output="screen",
                        arguments=["--ros-args", "--log-level", LaunchConfiguration("log_level")],
                        parameters=[
                            {"autostart": True},
                            {
                                "node_names": [
                                    "behavior_server",
                                    "bt_navigator",
                                ]
                            },
                        ],
                    ),
                ],
            ),
        ],
        condition=low_cpu_nav_enabled(["nav", "auto_nav"]),
    )

    delayed_nav2_navigation = TimerAction(
        period=LaunchConfiguration("nav_start_delay"),
        actions=[nav2_navigation, nav2_navigation_lite],
    )

    explore_light_navigation = GroupAction(
        [
            SetParameter(
                "bond_timeout",
                ParameterValue(
                    LaunchConfiguration("lifecycle_bond_timeout"),
                    value_type=float,
                ),
            ),
            Node(
                package="nav2_controller",
                executable="controller_server",
                output="screen",
                respawn=LaunchConfiguration("use_respawn"),
                respawn_delay=2.0,
                parameters=[LaunchConfiguration("nav_params_file")],
                arguments=["--ros-args", "--log-level", LaunchConfiguration("log_level")],
                remappings=[
                    ("/tf", "tf"),
                    ("/tf_static", "tf_static"),
                    ("cmd_vel", LaunchConfiguration("nav_controller_cmd_vel_topic")),
                ],
            ),
            Node(
                package="nav2_planner",
                executable="planner_server",
                name="planner_server",
                output="screen",
                respawn=LaunchConfiguration("use_respawn"),
                respawn_delay=2.0,
                parameters=[LaunchConfiguration("nav_params_file")],
                arguments=["--ros-args", "--log-level", LaunchConfiguration("log_level")],
                remappings=[
                    ("/tf", "tf"),
                    ("/tf_static", "tf_static"),
                ],
            ),
            Node(
                package="nav2_behaviors",
                executable="behavior_server",
                name="behavior_server",
                output="screen",
                respawn=LaunchConfiguration("use_respawn"),
                respawn_delay=2.0,
                parameters=[LaunchConfiguration("nav_params_file")],
                arguments=["--ros-args", "--log-level", LaunchConfiguration("log_level")],
                remappings=[
                    ("/tf", "tf"),
                    ("/tf_static", "tf_static"),
                    ("cmd_vel", LaunchConfiguration("nav_controller_cmd_vel_topic")),
                ],
            ),
            Node(
                package="nav2_bt_navigator",
                executable="bt_navigator",
                name="bt_navigator",
                output="screen",
                respawn=LaunchConfiguration("use_respawn"),
                respawn_delay=2.0,
                parameters=[LaunchConfiguration("nav_params_file")],
                arguments=["--ros-args", "--log-level", LaunchConfiguration("log_level")],
                remappings=[
                    ("/tf", "tf"),
                    ("/tf_static", "tf_static"),
                    ("goal_pose", LaunchConfiguration("nav2_goal_pose_topic")),
                ],
            ),
            Node(
                package="nav2_lifecycle_manager",
                executable="lifecycle_manager",
                name="lifecycle_manager_navigation",
                output="screen",
                arguments=["--ros-args", "--log-level", LaunchConfiguration("log_level")],
                parameters=[
                    {"autostart": False},
                    {
                        "node_names": [
                            "controller_server",
                            "planner_server",
                            "behavior_server",
                            "bt_navigator",
                        ]
                    },
                ],
            ),
        ],
        condition=enabled_for_mode("enable_nav", ["explore"]),
    )

    nav2_official_slam_navigation = GroupAction(
        [
            SetParameter(
                "bond_timeout",
                ParameterValue(
                    LaunchConfiguration("lifecycle_bond_timeout"),
                    value_type=float,
                ),
            ),
            SetRemap(src="goal_pose", dst=LaunchConfiguration("nav2_goal_pose_topic")),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    PathJoinSubstitution(
                        [FindPackageShare("nav2_bringup"), "launch", "bringup_launch.py"]
                    )
                ),
                launch_arguments={
                    "slam": "True",
                    "use_localization": "True",
                    "map": LaunchConfiguration("map"),
                    "params_file": LaunchConfiguration("nav_params_file"),
                    "use_sim_time": "false",
                    "autostart": "false",
                    "use_composition": LaunchConfiguration("use_composition"),
                    "use_respawn": LaunchConfiguration("use_respawn"),
                    "log_level": LaunchConfiguration("log_level"),
                }.items(),
            ),
        ],
        condition=enabled_for_mode("enable_nav", ["slam_nav"]),
    )

    explore_lite_node = Node(
        package="explore_lite",
        executable="explore",
        name="explore_node",
        output="screen",
        parameters=[
            LaunchConfiguration("explore_params_file"),
            {"use_sim_time": False},
        ],
        remappings=[
            ("/tf", "tf"),
            ("/tf_static", "tf_static"),
        ],
        condition=enabled_for_mode("enable_explore", ["explore"]),
    )

    slam_lifecycle_autostarter = Node(
        package="ddsm_car_control",
        executable="slam_lifecycle_autostarter",
        name="slam_lifecycle_autostarter",
        output="screen",
        parameters=[
            {
                "target_node": "/slam_toolbox",
                "check_period": 1.0,
                "request_timeout": 5.0,
            }
        ],
        condition=enabled_for_mode("enable_nav", ["slam_nav", "explore"]),
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
        condition=enabled_for_mode("enable_nav", ["slam_nav", "explore"]),
    )

    home_manager = Node(
        package="ddsm_car_control",
        executable="ddsm_home_manager",
        name="ddsm_home_manager",
        output="screen",
        parameters=[
            {
                "home_pose_file": LaunchConfiguration("home_pose_file"),
                "map_file": LaunchConfiguration("home_map_file"),
                "map_frame": "map",
                "base_frame": "base_link",
                "navigate_action": "navigate_to_pose",
                "tf_timeout": 1.0,
            }
        ],
        condition=enabled_for_mode("enable_home_manager", ["nav", "auto_nav", "slam_nav"]),
    )

    final_approach_navigator = Node(
        package="ddsm_car_control",
        executable="ddsm_final_approach_navigator",
        name="ddsm_final_approach_navigator",
        output="screen",
        parameters=[
            {
                "goal_topic": LaunchConfiguration("final_approach_goal_topic"),
                "navigate_action": "navigate_to_pose",
                "cmd_vel_topic": "/cmd_vel_nav",
                "scan_topic": "/scan",
                "map_frame": "map",
                "base_frame": "base_link",
                "staging_distance": 0.75,
                "use_staging_pose": False,
                "final_servo_xy_enabled": False,
                "final_xy_tolerance": 0.08,
                "final_yaw_tolerance": 0.18,
                "servo_timeout": 25.0,
                "max_final_linear_speed": 0.30,
                "max_final_lateral_speed": 0.18,
                "max_final_angular_speed": 1.35,
                "final_lateral_gain": 0.45,
                "allow_final_lateral_motion": True,
                "front_stop_distance": 0.30,
            }
        ],
        condition=enabled_for_mode("enable_final_approach", ["nav", "auto_nav", "slam_nav"]),
    )

    patrol_manager = Node(
        package="ddsm_car_control",
        executable="ddsm_patrol_manager",
        name="ddsm_patrol_manager",
        output="screen",
        parameters=[
            {
                "route_file": LaunchConfiguration("patrol_route_file"),
                "map_frame": "map",
                "navigate_action": "navigate_to_pose",
                "final_goal_topic": LaunchConfiguration("final_approach_goal_topic"),
                "final_status_topic": "/final_approach/status",
                "final_cancel_service": "/final_approach/cancel",
                "patrol_stop_topic": "/patrol/stop",
                "localization_ready_topic": "/localization/ready",
                "require_localization_ready": ParameterValue(
                    LaunchConfiguration("patrol_require_localization_ready"),
                    value_type=bool,
                ),
                "default_dwell_sec": 0.0,
                "retry_count": 1,
                "stop_on_failure": False,
                "final_approach_timeout": 90.0,
                "nav_goal_timeout": 180.0,
            }
        ],
        condition=enabled_for_mode("enable_patrol_manager", ["nav", "auto_nav"]),
    )

    waterplus_bridge = Node(
        package="ddsm_car_control",
        executable="ddsm_waterplus_bridge",
        name="ddsm_waterplus_bridge",
        output="screen",
        parameters=[
            {
                "route_file": LaunchConfiguration("patrol_route_file"),
                "waterplus_file": LaunchConfiguration("waterplus_waypoints_file"),
                "map_frame": "map",
                "route_id": "waterplus_route",
                "default_dwell_sec": 0.0,
                "default_waypoint_type": LaunchConfiguration(
                    "waterplus_default_waypoint_type"
                ),
                "default_final_approach": ParameterValue(
                    LaunchConfiguration("waterplus_default_final_approach"),
                    value_type=bool,
                ),
                "enable_goal_pose_alias": ParameterValue(
                    LaunchConfiguration("enable_waterplus_goal_pose_alias"),
                    value_type=bool,
                ),
                "goal_pose_topic": LaunchConfiguration("waterplus_goal_pose_topic"),
            }
        ],
        condition=enabled_for_mode("enable_waterplus_bridge", ["nav", "auto_nav"]),
    )

    semantic_map_server = Node(
        package="hotel_semantic_map",
        executable="semantic_map_server",
        name="hotel_semantic_map_server",
        output="screen",
        parameters=[
            {
                "manifest_file": LaunchConfiguration("semantic_map_manifest"),
                "marker_topic": "/semantic_map/markers",
                "status_topic": "/semantic_map/status",
                "republish_period": 5.0,
            }
        ],
        condition=enabled_for_mode("enable_semantic_map", ["nav", "auto_nav"]),
    )

    named_navigation_server = Node(
        package="hotel_semantic_map",
        executable="named_navigation_server",
        name="hotel_named_navigation_server",
        output="screen",
        parameters=[
            {
                "manifest_file": LaunchConfiguration("semantic_map_manifest"),
                "action_name": LaunchConfiguration("named_navigation_action"),
                "navigate_action": "navigate_to_pose",
                "final_goal_topic": LaunchConfiguration("final_approach_goal_topic"),
                "final_status_topic": "/final_approach/status",
                "localization_ready_topic": "/localization/ready",
                "amcl_pose_topic": "/amcl_pose",
                "goal_topic": "/hotel/mission/goal_destination",
                "cancel_topic": "/hotel/cancel",
                "status_topic": "/hotel/navigation_status",
                "require_localization_ready": ParameterValue(
                    LaunchConfiguration("named_navigation_require_localization"),
                    value_type=bool,
                ),
                "localization_wait_timeout": 60.0,
                "navigation_timeout": 300.0,
                "final_approach_timeout": 90.0,
                "nav_goal_timeout": 240.0,
                "cancel_patrol_on_goal": True,
            }
        ],
        condition=enabled_for_mode("enable_named_navigation", ["nav", "auto_nav"]),
    )

    mission_control = Node(
        package="ddsm_car_control",
        executable="ddsm_mission_control",
        name="ddsm_mission_control",
        output="screen",
        parameters=[
            {
                "state_file": LaunchConfiguration("mission_state_file"),
                "cmd_vel_topic": "/cmd_vel_nav",
                "zero_velocity_seconds": LaunchConfiguration(
                    "mission_zero_velocity_seconds"
                ),
                "zero_velocity_hz": LaunchConfiguration("mission_zero_velocity_hz"),
                "goal_request_topic": "/hotel/goal_destination",
                "hotel_goal_topic": "/hotel/mission/goal_destination",
                "hotel_cancel_topic": "/hotel/cancel",
                "patrol_pause_topic": "/patrol/pause",
                "patrol_resume_topic": "/patrol/resume",
                "patrol_stop_topic": "/patrol/stop",
                "home_go_topic": "/home/go",
                "home_cancel_topic": "/home/cancel",
                "final_goal_topic": LaunchConfiguration("final_approach_goal_topic"),
                "final_cancel_service": "/final_approach/cancel",
            }
        ],
        condition=enabled_for_mode("enable_mission_control", ["nav", "auto_nav", "slam_nav", "explore"]),
    )

    multifloor_manager = Node(
        package="ddsm_car_control",
        executable="ddsm_multifloor_manager",
        name="ddsm_multifloor_manager",
        output="screen",
        parameters=[
            {
                "building_config_file": LaunchConfiguration(
                    "multifloor_building_config_file"
                ),
                "state_file": LaunchConfiguration("multifloor_state_file"),
                "goal_topic": "/hotel/floor_goal",
                "arrived_topic": "/hotel/floor_transfer/arrived",
                "elevator_lobby_ready_topic": "/hotel/elevator/lobby_ready",
                "elevator_entered_topic": "/hotel/elevator/entered",
                "elevator_exited_topic": "/hotel/elevator/exited",
                "elevator_status_topic": "/hotel/elevator/status",
                "elevator_command_topic": "/hotel/elevator/command",
                "cancel_topic": "/hotel/floor_mission/cancel",
                "status_topic": "/hotel/floor_mission/status",
                "single_floor_goal_topic": "/hotel/goal_destination",
                "mission_cancel_service": "/hotel/mission/cancel_now",
                "initial_pose_topic": "/initialpose",
                "restart_script": "/home/sunrise/luka_ws/src/system/bringup/restart_nav_reset.sh",
                "restart_mode": "auto_nav",
                "restart_foxglove": "0",
                "current_floor_id": LaunchConfiguration("multifloor_current_floor_id"),
            }
        ],
        condition=enabled_for_mode("enable_multifloor_manager", ["nav", "auto_nav"]),
    )

    elevator_adapter = Node(
        package="ddsm_car_control",
        executable="ddsm_elevator_adapter",
        name="ddsm_elevator_adapter",
        output="screen",
        parameters=[
            {
                "backend": LaunchConfiguration("elevator_backend"),
                "command_topic": "/hotel/elevator/command",
                "status_topic": "/hotel/elevator/status",
                "manual_status_topic": "/hotel/elevator/manual/status",
                "manual_pending_command_topic": "/hotel/elevator/manual/pending_command",
                "initial_floor_id": LaunchConfiguration("multifloor_current_floor_id"),
            }
        ],
        condition=enabled_for_mode("enable_elevator_adapter", ["nav", "auto_nav"]),
    )

    elevator_entry_controller = Node(
        package="ddsm_car_control",
        executable="elevator_entry_controller",
        name="elevator_entry_controller",
        output="screen",
        parameters=[LaunchConfiguration("elevator_entry_params_file")],
        condition=enabled_for_mode(
            "enable_elevator_entry_controller", ["nav", "auto_nav"]
        ),
    )

    llm_agent = Node(
        package="nav_llm_agent",
        executable="agent_node",
        name="nav_llm_agent",
        output="screen",
        parameters=[
            {
                "waypoints_file": LaunchConfiguration("llm_waypoints_file"),
                "capabilities_file": LaunchConfiguration("llm_capabilities_file"),
                "ollama_url": LaunchConfiguration("llm_url"),
                "model": LaunchConfiguration("llm_model"),
                "llm_api": "openai",
                "building_config_file": LaunchConfiguration(
                    "multifloor_building_config_file"
                ),
                "transfer_state_file": "/home/sunrise/luka_ws/src/common/config/llm_floor_transfer_state.yaml",
                "restart_script": "/home/sunrise/luka_ws/src/system/bringup/restart_nav_reset.sh",
                "current_floor_id": LaunchConfiguration(
                    "multifloor_current_floor_id"
                ),
                "exit_waypoint": "wp_006",
                "use_sim_time": False,
                "dry_run": False,
            }
        ],
        condition=enabled_for_mode("enable_llm_agent", ["nav", "auto_nav"]),
    )

    delayed_nav_mission_services = TimerAction(
        period=LaunchConfiguration("mission_start_delay"),
        actions=[
            mission_control,
            elevator_adapter,
            elevator_entry_controller,
            multifloor_manager,
            home_manager,
            final_approach_navigator,
            patrol_manager,
            waterplus_bridge,
            semantic_map_server,
            named_navigation_server,
            llm_agent,
        ],
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
            feedback_enabled_arg,
            read_speed_feedback_arg,
            feedback_freq_arg,
            max_linear_speed_arg,
            max_angular_speed_arg,
            max_motor_rpm_arg,
            mecanum_forward_scale_arg,
            mecanum_lateral_scale_arg,
            mecanum_lateral_direction_arg,
            mecanum_angular_scale_arg,
            acceleration_arg,
            timeout_arg,
            mode_arg,
            enable_slam_arg,
            enable_nav_arg,
            low_cpu_nav_arg,
            enable_auto_localizer_arg,
            enable_patrol_manager_arg,
            enable_waterplus_bridge_arg,
            enable_semantic_map_arg,
            enable_named_navigation_arg,
            enable_mission_control_arg,
            enable_multifloor_manager_arg,
            enable_elevator_adapter_arg,
            enable_elevator_entry_controller_arg,
            enable_llm_agent_arg,
            llm_waypoints_file_arg,
            llm_capabilities_file_arg,
            llm_url_arg,
            llm_model_arg,
            elevator_entry_params_file_arg,
            elevator_backend_arg,
            enable_explore_arg,
            enable_home_manager_arg,
            enable_final_approach_arg,
            enable_lateral_escape_guard_arg,
            navigation_motion_mode_arg,
            enable_base_driver_arg,
            enable_imu_arg,
            imu_port_arg,
            imu_baud_arg,
            imu_protocol_arg,
            imu_configure_output_arg,
            imu_heading_mode_arg,
            heading_pid_enabled_arg,
            heading_feedback_source_arg,
            heading_pid_kp_arg,
            heading_pid_max_wz_arg,
            heading_hold_min_vx_arg,
            heading_hold_angular_deadband_arg,
            enable_teleop_arg,
            teleop_speed_arg,
            teleop_turn_arg,
            enable_ekf_arg,
            enable_lidar_arg,
            start_lidar_driver_arg,
            enable_dual_lidar_arg,
            low_lidar_ip_arg,
            low_lidar_port_arg,
            low_lidar_x_arg,
            low_lidar_y_arg,
            low_lidar_z_arg,
            low_lidar_yaw_arg,
            low_lidar_inverted_arg,
            low_lidar_keep_min_deg_arg,
            low_lidar_keep_max_deg_arg,
            enable_scan_deskew_arg,
            enable_depth_camera_arg,
            enable_colored_point_cloud_arg,
            enable_depth_obstacle_fusion_arg,
            enable_semantic_mapping_arg,
            semantic_floor_id_arg,
            semantic_output_file_arg,
            camera_x_arg,
            camera_y_arg,
            camera_z_arg,
            enable_laser_tf_arg,
            laser_x_arg,
            laser_y_arg,
            laser_z_arg,
            laser_yaw_arg,
            lidar_scan_frequency_arg,
            lidar_topic_name_arg,
            scan_publish_frequency_arg,
            map_arg,
            home_pose_file_arg,
            home_map_file_arg,
            auto_localizer_last_pose_file_arg,
            auto_localizer_enable_rotation_arg,
            auto_localizer_max_rotation_speed_arg,
            auto_localizer_rotation_clearance_arg,
            auto_localizer_enable_escape_arg,
            auto_localizer_escape_speed_arg,
            auto_localizer_escape_lateral_direction_arg,
            auto_localizer_escape_duration_arg,
            auto_localizer_escape_max_attempts_arg,
            auto_localizer_warm_start_timeout_arg,
            auto_localizer_global_timeout_arg,
            auto_localizer_xy_std_threshold_arg,
            auto_localizer_yaw_std_threshold_arg,
            patrol_route_file_arg,
            mission_state_file_arg,
            mission_zero_velocity_seconds_arg,
            mission_zero_velocity_hz_arg,
            multifloor_building_config_file_arg,
            multifloor_state_file_arg,
            multifloor_current_floor_id_arg,
            semantic_map_manifest_arg,
            named_navigation_action_arg,
            named_navigation_require_localization_arg,
            waterplus_waypoints_file_arg,
            waterplus_default_waypoint_type_arg,
            waterplus_default_final_approach_arg,
            enable_waterplus_goal_pose_alias_arg,
            waterplus_goal_pose_topic_arg,
            nav2_goal_pose_topic_arg,
            final_approach_goal_topic_arg,
            nav_controller_cmd_vel_topic_arg,
            lateral_escape_direction_sign_arg,
            patrol_require_localization_ready_arg,
            nav_params_file_arg,
            amcl_transform_tolerance_arg,
            slam_params_file_arg,
            explore_params_file_arg,
            slam_map_update_interval_arg,
            ekf_params_file_arg,
            map_publish_frequency_arg,
            lifecycle_bond_timeout_arg,
            nav_start_delay_arg,
            nav_node_batch_delay_arg,
            mission_start_delay_arg,
            autostart_arg,
            use_composition_arg,
            use_respawn_arg,
            log_level_arg,
            robot_bringup,
            low_lidar_proxy,
            low_lidar_driver,
            low_lidar_tf,
            dual_laser_fusion,
            depth_camera,
            depth_camera_tf,
            depth_camera_optical_tf,
            depth_camera_color_optical_tf,
            colored_point_cloud_relay,
            depth_obstacle_monitor,
            semantic_mapping_recorder,
            scan_throttler,
            teleop_keyboard,
            slam_toolbox,
            map_republisher,
            nav2_localization,
            auto_localizer,
            lateral_escape_guard,
            delayed_nav2_navigation,
            explore_light_navigation,
            nav2_official_slam_navigation,
            explore_lite_node,
            slam_lifecycle_autostarter,
            navigation_autostarter,
            delayed_nav_mission_services,
        ]
    )
