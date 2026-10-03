from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def test_unified_launch_selects_slam_and_nav_modes():
    launch_text = (PACKAGE_ROOT / "launch" / "ddsm_bringup.launch.py").read_text(
        encoding="utf-8"
    )

    assert '"mode"' in launch_text
    assert '"bringup"' in launch_text
    assert '"slam"' in launch_text
    assert '"nav"' in launch_text
    assert '"slam_nav"' in launch_text
    assert '"explore"' in launch_text
    assert '"auto_nav"' in launch_text
    assert "enabled_for_mode" in launch_text
    assert '"enable_slam"' in launch_text
    assert '"enable_nav"' in launch_text
    assert "async_slam_toolbox_node" in launch_text
    assert "bringup_launch.py" in launch_text
    assert '"slam": "True"' in launch_text
    assert '"use_localization": "True"' in launch_text
    assert "localization_launch.py" in launch_text
    assert 'executable="controller_server"' in launch_text
    assert 'executable="bt_navigator"' in launch_text
    assert 'name="lifecycle_manager_navigation"' in launch_text
    assert 'SetRemap(src="/map", dst="/slam_map")' in launch_text
    assert "executable=\"map_republisher\"" in launch_text
    assert "executable=\"nav_lifecycle_autostarter\"" in launch_text
    assert "executable=\"slam_lifecycle_autostarter\"" in launch_text


def test_auto_nav_mode_runs_amcl_auto_localizer_before_navigation():
    launch_text = (PACKAGE_ROOT / "launch" / "ddsm_bringup.launch.py").read_text(
        encoding="utf-8"
    )
    setup_text = (PACKAGE_ROOT / "setup.py").read_text(encoding="utf-8")

    assert '"auto_nav"' in launch_text
    assert '"enable_auto_localizer"' in launch_text
    assert '"auto_localizer_last_pose_file"' in launch_text
    assert '"auto_localizer_enable_rotation"' in launch_text
    assert 'executable="ddsm_auto_localizer"' in launch_text
    assert 'condition=enabled_for_mode("enable_auto_localizer", ["auto_nav"])' in launch_text
    assert 'condition=enabled_for_mode("enable_nav", ["nav", "auto_nav"])' in launch_text
    assert (
        'condition=enabled_for_mode("enable_home_manager", ["nav", "auto_nav", "slam_nav"])'
        in launch_text
    )
    assert (
        'condition=enabled_for_mode("enable_final_approach", ["nav", "auto_nav", "slam_nav"])'
        in launch_text
    )
    assert "ddsm_auto_localizer = ddsm_car_control.ddsm_auto_localizer:main" in setup_text


def test_auto_nav_exposes_low_cpu_navigation_path_for_j1900_ipc():
    launch_text = (PACKAGE_ROOT / "launch" / "ddsm_bringup.launch.py").read_text(
        encoding="utf-8"
    )

    assert '"low_cpu_nav"' in launch_text
    assert "low_cpu_nav_enabled" in launch_text
    assert "low_cpu_nav_disabled" in launch_text
    assert "nav2_navigation_lite = GroupAction" in launch_text
    assert 'condition=low_cpu_nav_enabled(["nav", "auto_nav"])' in launch_text
    assert 'condition=low_cpu_nav_disabled(["nav", "auto_nav"])' in launch_text
    assert '"lifecycle_manager_navigation_safety"' in launch_text


def test_default_nav_avoids_forced_in_place_rotation_near_edges():
    config_text = (PACKAGE_ROOT / "config" / "nav2_params.yaml").read_text(
        encoding="utf-8"
    )

    follow_path_block = config_text.split("FollowPath:", 1)[1].split(
        "local_costmap:", 1
    )[0]
    assert "plugin: nav2_regulated_pure_pursuit_controller::RegulatedPurePursuitController" in follow_path_block
    assert "use_rotate_to_heading: false" in follow_path_block
    assert "rotate_to_heading_min_angle: 0.8" in follow_path_block


def test_mecanum_dwb_nav_profile_allows_lateral_motion():
    config_text = (
        PACKAGE_ROOT / "config" / "nav2_mecanum_dwb_params.yaml"
    ).read_text(encoding="utf-8")

    assert "plugin: dwb_core::DWBLocalPlanner" in config_text
    assert "controller_frequency: 3.0" in config_text
    assert "max_vel_x: 0.22" in config_text
    assert "min_vel_x: -0.04" in config_text
    assert "max_vel_y: 0.12" in config_text
    assert "min_vel_y: -0.12" in config_text
    assert "min_speed_xy: 0.05" in config_text
    assert "vx_samples: 5" in config_text
    assert "vy_samples: 5" in config_text
    assert "vtheta_samples: 7" in config_text
    assert "sim_time: 0.8" in config_text
    assert "trans_stopped_velocity: 0.03" in config_text


def test_unified_launch_exposes_patrol_manager_for_navigation_modes():
    launch_text = (PACKAGE_ROOT / "launch" / "ddsm_bringup.launch.py").read_text(
        encoding="utf-8"
    )
    setup_text = (PACKAGE_ROOT / "setup.py").read_text(encoding="utf-8")
    package_text = (PACKAGE_ROOT / "package.xml").read_text(encoding="utf-8")

    assert '"enable_patrol_manager"' in launch_text
    assert '"patrol_route_file"' in launch_text
    assert '"patrol_require_localization_ready"' in launch_text
    assert 'executable="ddsm_patrol_manager"' in launch_text
    assert (
        'condition=enabled_for_mode("enable_patrol_manager", ["nav", "auto_nav"])'
        in launch_text
    )
    assert "ddsm_patrol_manager = ddsm_car_control.ddsm_patrol_manager:main" in setup_text
    assert "<exec_depend>visualization_msgs</exec_depend>" in package_text


def test_unified_launch_exposes_waterplus_bridge_for_foxglove_waypoints():
    launch_text = (PACKAGE_ROOT / "launch" / "ddsm_bringup.launch.py").read_text(
        encoding="utf-8"
    )
    setup_text = (PACKAGE_ROOT / "setup.py").read_text(encoding="utf-8")
    package_text = (PACKAGE_ROOT / "package.xml").read_text(encoding="utf-8")

    assert '"enable_waterplus_bridge"' in launch_text
    assert '"waterplus_waypoints_file"' in launch_text
    assert '"waterplus_default_waypoint_type"' in launch_text
    assert '"waterplus_default_final_approach"' in launch_text
    assert '"enable_waterplus_goal_pose_alias"' in launch_text
    assert '"waterplus_goal_pose_topic"' in launch_text
    assert 'default_value="/goal_pose"' in launch_text
    assert '"nav2_goal_pose_topic"' in launch_text
    assert 'default_value="/nav_goal_pose"' in launch_text
    assert '"final_approach_goal_topic"' in launch_text
    assert 'default_value="/final_approach/goal_pose"' in launch_text
    assert (
        '("goal_pose", LaunchConfiguration("nav2_goal_pose_topic"))'
        in launch_text
    )
    assert '"goal_topic": LaunchConfiguration("final_approach_goal_topic")' in launch_text
    assert '"final_goal_topic": LaunchConfiguration("final_approach_goal_topic")' in launch_text
    assert 'executable="ddsm_waterplus_bridge"' in launch_text
    assert (
        'condition=enabled_for_mode("enable_waterplus_bridge", ["nav", "auto_nav"])'
        in launch_text
    )
    assert (
        "ddsm_waterplus_bridge = ddsm_car_control.waterplus_waypoint_bridge:main"
        in setup_text
    )
    assert "<exec_depend>waterplus_map_tools</exec_depend>" in package_text


def test_unified_launch_exposes_mission_control_for_navigation_modes():
    launch_text = (PACKAGE_ROOT / "launch" / "ddsm_bringup.launch.py").read_text(
        encoding="utf-8"
    )
    setup_text = (PACKAGE_ROOT / "setup.py").read_text(encoding="utf-8")

    assert '"enable_mission_control"' in launch_text
    assert '"mission_state_file"' in launch_text
    assert '"mission_zero_velocity_seconds"' in launch_text
    assert '"mission_zero_velocity_hz"' in launch_text
    assert '"goal_topic": "/hotel/mission/goal_destination"' in launch_text
    assert '"goal_request_topic": "/hotel/goal_destination"' in launch_text
    assert '"hotel_goal_topic": "/hotel/mission/goal_destination"' in launch_text
    assert 'executable="ddsm_mission_control"' in launch_text
    assert (
        'condition=enabled_for_mode("enable_mission_control", ["nav", "auto_nav", "slam_nav", "explore"])'
        in launch_text
    )
    assert "ddsm_mission_control = ddsm_car_control.ddsm_mission_control:main" in setup_text


def test_unified_launch_exposes_multifloor_manager_for_navigation_modes():
    launch_text = (PACKAGE_ROOT / "launch" / "ddsm_bringup.launch.py").read_text(
        encoding="utf-8"
    )
    setup_text = (PACKAGE_ROOT / "setup.py").read_text(encoding="utf-8")
    package_text = (PACKAGE_ROOT / "package.xml").read_text(encoding="utf-8")
    config_text = (PACKAGE_ROOT / "config" / "multifloor_building.yaml").read_text(
        encoding="utf-8"
    )

    assert '"enable_multifloor_manager"' in launch_text
    assert '"multifloor_building_config_file"' in launch_text
    assert '"multifloor_state_file"' in launch_text
    assert 'executable="ddsm_multifloor_manager"' in launch_text
    assert '"goal_topic": "/hotel/floor_goal"' in launch_text
    assert '"single_floor_goal_topic": "/hotel/goal_destination"' in launch_text
    assert '"mission_cancel_service": "/hotel/mission/cancel_now"' in launch_text
    assert (
        'condition=enabled_for_mode("enable_multifloor_manager", ["nav", "auto_nav"])'
        in launch_text
    )
    assert (
        "ddsm_multifloor_manager = ddsm_car_control.ddsm_multifloor_manager:main"
        in setup_text
    )
    assert "<exec_depend>python3-yaml</exec_depend>" in package_text
    assert "display_name: 门口" in config_text
    assert "destination_id: wp_003" in config_text


def test_unified_launch_exposes_explore_mode():
    launch_text = (PACKAGE_ROOT / "launch" / "ddsm_bringup.launch.py").read_text(
        encoding="utf-8"
    )
    package_text = (PACKAGE_ROOT / "package.xml").read_text(encoding="utf-8")

    assert '"explore"' in launch_text
    assert '"enable_explore"' in launch_text
    assert '"explore_params_file"' in launch_text
    assert "explore_lite" in launch_text
    assert "executable=\"explore\"" in launch_text
    assert '"enable_slam"' in launch_text
    assert '"enable_nav"' in launch_text
    assert 'condition=enabled_for_mode("enable_explore", ["explore"])' in launch_text
    assert "<exec_depend>explore_lite</exec_depend>" in package_text


def test_explore_lite_uses_live_map_topics_for_foxglove_mapping_view():
    config_text = (PACKAGE_ROOT / "config" / "explore_lite.yaml").read_text(
        encoding="utf-8"
    )

    assert "costmap_topic: /map" in config_text
    assert "costmap_updates_topic: /map_updates" in config_text
    assert "visualize: true" in config_text
    assert "planner_frequency: 0.15" in config_text
    assert "progress_timeout: 90.0" in config_text
    assert "transform_tolerance: 1.0" in config_text
    assert "min_frontier_size: 1.0" in config_text


def test_explore_nav2_params_reduce_slam_load_for_realtime_tf():
    config_text = (PACKAGE_ROOT / "config" / "nav2_explore_params.yaml").read_text(
        encoding="utf-8"
    )

    assert "throttle_scans: 1" in config_text
    assert "map_update_interval: 0.7" in config_text
    assert "minimum_time_interval: 0.2" in config_text
    assert "minimum_travel_distance: 0.2" in config_text
    assert "minimum_travel_heading: 0.15" in config_text
    assert "scan_buffer_size: 10" in config_text
    assert "restamp_tf: true" in config_text
    assert "do_loop_closing: false" in config_text
    assert "controller_frequency: 3.0" in config_text
    assert "costmap_update_timeout: 2.0" in config_text
    assert "failure_tolerance: 2.0" in config_text
    assert "update_frequency: 3.0" in config_text
    assert "publish_frequency: 1.5" in config_text
    assert "max_linear_vel: 0.22" in config_text
    assert "inflation_radius: 0.65" in config_text
    assert "footprint_padding: 0.06" in config_text
    assert "use_collision_detection: true" in config_text
    assert "transform_tolerance: 1.0" in config_text
    assert "max_allowed_time_to_collision_up_to_carrot: 0.6" in config_text
    assert "footprint_clearing_enabled: true" in config_text
    global_costmap_block = config_text.split("global_costmap:", 1)[1].split(
        "map_saver:", 1
    )[0]
    global_plugins_block = global_costmap_block.split("plugins:", 1)[1].split(
        "obstacle_layer:", 1
    )[0]
    assert "- static_layer" in global_plugins_block
    assert "- obstacle_layer" in global_plugins_block
    assert "- inflation_layer" in global_plugins_block
    assert "enabled: true" in global_costmap_block
    assert "smoothing_frequency: 5.0" in config_text


def test_explore_ekf_params_reduce_filter_load():
    config_text = (PACKAGE_ROOT / "config" / "ekf_explore.yaml").read_text(
        encoding="utf-8"
    )

    assert "frequency: 3.0" in config_text
    assert "print_diagnostics: false" in config_text


def test_unified_launch_passes_lidar_scan_frequency_to_robot_bringup():
    launch_text = (PACKAGE_ROOT / "launch" / "ddsm_bringup.launch.py").read_text(
        encoding="utf-8"
    )
    robot_launch_text = (
        PACKAGE_ROOT / "launch" / "ddsm_robot_bringup.launch.py"
    ).read_text(encoding="utf-8")

    assert '"lidar_scan_frequency"' in launch_text
    assert 'default_value="10.0"' in launch_text
    assert '"lidar_scan_frequency": LaunchConfiguration("lidar_scan_frequency")' in launch_text
    assert '"lidar_scan_frequency"' in robot_launch_text
    assert '"scan_frequency": ParameterValue(' in robot_launch_text
    assert '"lidar_topic_name": PythonExpression(' in launch_text
    assert "'/scan_raw' if ('" in launch_text
    assert '"lidar_topic_name"' in robot_launch_text
    assert '"topic_name": LaunchConfiguration("lidar_topic_name")' in robot_launch_text


def test_unified_launch_passes_base_timeout_to_robot_bringup():
    launch_text = (PACKAGE_ROOT / "launch" / "ddsm_bringup.launch.py").read_text(
        encoding="utf-8"
    )

    assert 'timeout_arg = DeclareLaunchArgument(' in launch_text
    assert '"timeout"' in launch_text
    assert 'default_value="0.4"' in launch_text
    assert '"timeout": LaunchConfiguration("timeout")' in launch_text


def test_unified_launch_exposes_scan_throttler_for_low_cpu_explore():
    launch_text = (PACKAGE_ROOT / "launch" / "ddsm_bringup.launch.py").read_text(
        encoding="utf-8"
    )
    setup_text = (PACKAGE_ROOT / "setup.py").read_text(encoding="utf-8")

    assert '"scan_publish_frequency"' in launch_text
    assert 'executable="scan_throttler"' in launch_text
    assert '"input_topic": PythonExpression(' in launch_text
    assert "'/scan_deskewed' if '" in launch_text
    assert '"output_topic": "/scan"' in launch_text
    assert '"publish_frequency": LaunchConfiguration("scan_publish_frequency")' in launch_text
    assert 'condition=IfCondition(' in launch_text
    assert 'LaunchConfiguration("scan_publish_frequency")' in launch_text
    assert "scan_throttler = ddsm_car_control.scan_throttler:main" in setup_text


def test_unified_launch_routes_lidar_through_motion_deskewer():
    launch_text = (PACKAGE_ROOT / "launch" / "ddsm_bringup.launch.py").read_text(
        encoding="utf-8"
    )
    robot_launch_text = (
        PACKAGE_ROOT / "launch" / "ddsm_robot_bringup.launch.py"
    ).read_text(encoding="utf-8")
    setup_text = (PACKAGE_ROOT / "setup.py").read_text(encoding="utf-8")
    deskewer_text = (
        PACKAGE_ROOT / "ddsm_car_control" / "laser_scan_deskewer.py"
    ).read_text(encoding="utf-8")

    assert '"enable_scan_deskew"' in launch_text
    assert '"scan_deskew_input_topic": "/scan_raw"' in launch_text
    assert '"scan_deskew_output_topic": PythonExpression(' in launch_text
    assert 'executable="laser_scan_deskewer"' in robot_launch_text
    assert '"odom_topic": LaunchConfiguration("scan_deskew_odom_topic")' in robot_launch_text
    assert "laser_scan_deskewer = ddsm_car_control.laser_scan_deskewer:main" in setup_text
    assert "self.create_publisher(LaserScan, output_topic, output_qos)" in deskewer_text
    assert "reliability=ReliabilityPolicy.RELIABLE" in deskewer_text


def test_explore_mode_uses_async_slam_with_navigation_for_low_cpu_mapping():
    launch_text = (PACKAGE_ROOT / "launch" / "ddsm_bringup.launch.py").read_text(
        encoding="utf-8"
    )

    slam_block = launch_text.split("slam_toolbox = GroupAction", 1)[1].split(
        "map_republisher = Node", 1
    )[0]
    map_republisher_block = launch_text.split("map_republisher = Node", 1)[1].split(
        "nav2_localization = GroupAction", 1
    )[0]
    official_slam_nav_block = launch_text.split(
        "nav2_official_slam_navigation = GroupAction", 1
    )[1].split("explore_lite_node = Node", 1)[0]
    nav2_navigation_block = launch_text.split("nav2_navigation = GroupAction", 1)[
        1
    ].split("nav2_official_slam_navigation = GroupAction", 1)[0]
    explore_light_navigation_block = launch_text.split(
        "explore_light_navigation = GroupAction", 1
    )[1].split("nav2_official_slam_navigation = GroupAction", 1)[0]
    robot_bringup_block = launch_text.split("robot_bringup = IncludeLaunchDescription", 1)[
        1
    ].split("slam_toolbox_node = LifecycleNode", 1)[0]

    assert 'condition=enabled_for_mode("enable_slam", ["slam", "explore"])' in slam_block
    assert (
        'condition=enabled_for_mode("enable_slam", ["slam", "explore"])'
        in map_republisher_block
    )
    assert "async_slam_toolbox_node" in launch_text
    assert 'condition=low_cpu_nav_disabled(["nav", "auto_nav"])' in nav2_navigation_block
    assert 'condition=low_cpu_nav_enabled(["nav", "auto_nav"])' in nav2_navigation_block
    assert 'condition=enabled_for_mode("enable_nav", ["explore"])' in explore_light_navigation_block
    assert '"slam": "True"' in official_slam_nav_block
    assert (
        'condition=enabled_for_mode("enable_nav", ["slam_nav"])'
        in official_slam_nav_block
    )
    assert 'condition=enabled_for_mode("enable_explore", ["explore"])' in launch_text
    assert '"ekf_params_file": LaunchConfiguration("ekf_params_file")' in robot_bringup_block
    assert "ekf_imu_yaw_rate.yaml" in launch_text


def test_explore_mode_uses_lightweight_nav2_nodes_only():
    launch_text = (PACKAGE_ROOT / "launch" / "ddsm_bringup.launch.py").read_text(
        encoding="utf-8"
    )

    explore_light_navigation_block = launch_text.split(
        "explore_light_navigation = GroupAction", 1
    )[1].split("nav2_official_slam_navigation = GroupAction", 1)[0]

    for executable in [
        "controller_server",
        "planner_server",
        "behavior_server",
        "bt_navigator",
        "lifecycle_manager",
    ]:
        assert f'executable="{executable}"' in explore_light_navigation_block

    assert '"node_names": [' in explore_light_navigation_block
    for lifecycle_node in [
        '"controller_server"',
        '"planner_server"',
        '"behavior_server"',
        '"bt_navigator"',
    ]:
        assert lifecycle_node in explore_light_navigation_block
    assert '{"autostart": False}' in explore_light_navigation_block

    for unnecessary_node in [
        "smoother_server",
        "route_server",
        "waypoint_follower",
        "velocity_smoother",
        "collision_monitor",
        "docking_server",
    ]:
        assert unnecessary_node not in explore_light_navigation_block


def test_slam_nav_launch_waits_for_slam_tf_before_starting_navigation():
    launch_text = (PACKAGE_ROOT / "launch" / "ddsm_bringup.launch.py").read_text(
        encoding="utf-8"
    )
    slam_nav_block = launch_text.split(
        "nav2_official_slam_navigation = GroupAction", 1
    )[1].split("navigation_autostarter = Node", 1)[0]

    assert '"autostart": "false"' in slam_nav_block
    assert '"autostart": LaunchConfiguration("autostart")' not in slam_nav_block
    assert 'condition=enabled_for_mode("enable_nav", ["nav", "auto_nav"])' in launch_text
    assert 'condition=enabled_for_mode("enable_nav", ["explore"])' in launch_text
    assert 'condition=enabled_for_mode("enable_nav", ["slam_nav"])' in launch_text


def test_unified_launch_passes_component_flags_to_robot_bringup():
    launch_text = (PACKAGE_ROOT / "launch" / "ddsm_bringup.launch.py").read_text(
        encoding="utf-8"
    )

    assert '"enable_base_driver": LaunchConfiguration("enable_base_driver")' in launch_text
    assert '"enable_imu": LaunchConfiguration("enable_imu")' in launch_text
    assert '"enable_ekf": LaunchConfiguration("enable_ekf")' in launch_text
    assert '"enable_lidar": LaunchConfiguration("enable_lidar")' in launch_text
    assert '"enable_laser_tf": LaunchConfiguration("enable_laser_tf")' in launch_text
    assert '"ekf_params_file": LaunchConfiguration("ekf_params_file")' in launch_text
    assert '"max_linear_speed": LaunchConfiguration("max_linear_speed")' in launch_text
    assert '"imu_heading_mode": LaunchConfiguration("imu_heading_mode")' in launch_text


def test_unified_launch_passes_heading_hold_params_to_robot_bringup():
    launch_text = (PACKAGE_ROOT / "launch" / "ddsm_bringup.launch.py").read_text(
        encoding="utf-8"
    )

    assert '"heading_pid_enabled"' in launch_text
    assert '"heading_feedback_source"' in launch_text
    assert '"heading_pid_kp"' in launch_text
    assert '"heading_pid_max_wz"' in launch_text
    assert '"heading_hold_min_vx"' in launch_text
    assert '"heading_hold_angular_deadband"' in launch_text
    assert '"heading_pid_enabled": LaunchConfiguration("heading_pid_enabled")' in launch_text
    assert '"heading_feedback_source": LaunchConfiguration("heading_feedback_source")' in launch_text
    assert '"heading_pid_kp": LaunchConfiguration("heading_pid_kp")' in launch_text
    assert '"heading_pid_max_wz": LaunchConfiguration("heading_pid_max_wz")' in launch_text
    assert '"heading_hold_min_vx": LaunchConfiguration("heading_hold_min_vx")' in launch_text
    assert '"heading_hold_angular_deadband": LaunchConfiguration(' in launch_text


def test_unified_launch_passes_mecanum_motion_ratio_params_to_robot_bringup():
    launch_text = (PACKAGE_ROOT / "launch" / "ddsm_bringup.launch.py").read_text(
        encoding="utf-8"
    )

    for name in (
        "mecanum_forward_scale",
        "mecanum_lateral_scale",
        "mecanum_angular_scale",
    ):
        assert f'"{name}"' in launch_text
        assert f'"{name}": LaunchConfiguration("{name}")' in launch_text

    assert '"mecanum_lateral_direction"' in launch_text
    assert '"mecanum_lateral_direction": LaunchConfiguration(' in launch_text


def test_nested_base_launches_forward_mecanum_lateral_direction():
    robot_text = (PACKAGE_ROOT / "launch" / "ddsm_robot_bringup.launch.py").read_text(
        encoding="utf-8"
    )
    car_text = (PACKAGE_ROOT / "launch" / "ddsm_car.launch.py").read_text(
        encoding="utf-8"
    )
    zdt_text = (PACKAGE_ROOT / "launch" / "zdt_y42_mecanum.launch.py").read_text(
        encoding="utf-8"
    )

    assert '"mecanum_lateral_direction"' in robot_text
    assert '"mecanum_lateral_direction": LaunchConfiguration(' in robot_text
    assert '"mecanum_lateral_direction"' in car_text
    assert '"mecanum_lateral_direction": LaunchConfiguration(' in car_text
    assert '"mecanum_lateral_direction"' in zdt_text
    assert 'LaunchConfiguration("mecanum_lateral_direction"), value_type=int' in zdt_text


def test_unified_launch_passes_laser_extrinsics_to_robot_bringup():
    launch_text = (PACKAGE_ROOT / "launch" / "ddsm_bringup.launch.py").read_text(
        encoding="utf-8"
    )

    for name, default in [
        ("laser_x", "-0.065"),
        ("laser_y", "0.0"),
        ("laser_z", "0.42"),
        ("laser_yaw", "0.0"),
    ]:
        assert f'"{name}"' in launch_text
        assert f'default_value="{default}"' in launch_text
        assert f'"{name}": LaunchConfiguration("{name}")' in launch_text


def test_unified_launch_exposes_imu_heading_mode():
    launch_text = (PACKAGE_ROOT / "launch" / "ddsm_bringup.launch.py").read_text(
        encoding="utf-8"
    )

    assert '"imu_heading_mode"' in launch_text
    assert 'default_value="relative"' in launch_text


def test_unified_launch_exposes_adjustable_slam_map_update_interval():
    launch_text = (PACKAGE_ROOT / "launch" / "ddsm_bringup.launch.py").read_text(
        encoding="utf-8"
    )

    assert '"slam_map_update_interval"' in launch_text
    assert 'default_value="0.15"' in launch_text
    assert '"map_update_interval": ParameterValue(' in launch_text
    assert 'LaunchConfiguration("slam_map_update_interval")' in launch_text


def test_unified_launch_defaults_drive_speed_limit_to_03_mps():
    launch_text = (PACKAGE_ROOT / "launch" / "ddsm_bringup.launch.py").read_text(
        encoding="utf-8"
    )

    assert '"max_linear_speed"' in launch_text
    assert 'default_value="0.3"' in launch_text


def test_unified_launch_defaults_map_publish_frequency_to_6hz():
    launch_text = (PACKAGE_ROOT / "launch" / "ddsm_bringup.launch.py").read_text(
        encoding="utf-8"
    )
    map_frequency_block = launch_text.split(
        "map_publish_frequency_arg = DeclareLaunchArgument", 1
    )[1].split("autostart_arg = DeclareLaunchArgument", 1)[0]

    assert '"map_publish_frequency"' in map_frequency_block
    assert 'default_value="6.0"' in map_frequency_block


def test_unified_launch_sets_nav2_lifecycle_bond_timeout_explicitly():
    launch_text = (PACKAGE_ROOT / "launch" / "ddsm_bringup.launch.py").read_text(
        encoding="utf-8"
    )

    assert '"lifecycle_bond_timeout"' in launch_text
    assert 'default_value="180.0"' in launch_text
    assert "SetParameter(" in launch_text
    assert '"bond_timeout"' in launch_text
    assert 'LaunchConfiguration("lifecycle_bond_timeout")' in launch_text


def test_saved_map_navigation_stages_navigation_nodes_after_localization():
    launch_text = (PACKAGE_ROOT / "launch" / "ddsm_bringup.launch.py").read_text(
        encoding="utf-8"
    )

    assert "TimerAction" in launch_text
    assert '"nav_start_delay"' in launch_text
    assert 'default_value="45.0"' in launch_text
    assert "delayed_nav2_navigation = TimerAction(" in launch_text
    assert 'period=LaunchConfiguration("nav_start_delay")' in launch_text
    assert "actions=[nav2_navigation, nav2_navigation_lite]" in launch_text
    assert "delayed_nav2_navigation," in launch_text


def test_saved_map_navigation_staggers_navigation_server_process_creation():
    launch_text = (PACKAGE_ROOT / "launch" / "ddsm_bringup.launch.py").read_text(
        encoding="utf-8"
    )

    assert '"nav_node_batch_delay"' in launch_text
    assert 'default_value="12.0"' in launch_text
    assert 'period=LaunchConfiguration("nav_node_batch_delay")' in launch_text
    assert '"2.0 * ", LaunchConfiguration("nav_node_batch_delay")' in launch_text


def test_saved_map_navigation_starts_three_small_lifecycle_batches_in_order():
    launch_text = (PACKAGE_ROOT / "launch" / "ddsm_bringup.launch.py").read_text(
        encoding="utf-8"
    )
    saved_map_navigation_block = launch_text.split(
        "nav2_navigation = GroupAction", 1
    )[1].split("nav2_navigation_lite = GroupAction", 1)[0]

    assert 'name="lifecycle_manager_navigation_core"' in saved_map_navigation_block
    assert 'name="lifecycle_manager_navigation_behavior"' in saved_map_navigation_block
    assert 'name="lifecycle_manager_navigation_safety"' in saved_map_navigation_block
    assert '"0.5 * ", LaunchConfiguration("nav_node_batch_delay")' in saved_map_navigation_block
    assert '"1.5 * ", LaunchConfiguration("nav_node_batch_delay")' in saved_map_navigation_block
    assert '"2.5 * ", LaunchConfiguration("nav_node_batch_delay")' in saved_map_navigation_block
    assert 'name="lifecycle_manager_navigation"' not in saved_map_navigation_block
    assert saved_map_navigation_block.count('{"autostart": True}') == 3


def test_saved_map_navigation_does_not_use_external_lifecycle_startup_service():
    launch_text = (PACKAGE_ROOT / "launch" / "ddsm_bringup.launch.py").read_text(
        encoding="utf-8"
    )

    assert "saved_map_navigation_autostarter = Node" not in launch_text
    autostarter_block = launch_text.split("navigation_autostarter = Node", 1)[1].split(
        "home_manager = Node", 1
    )[0]
    assert '["slam_nav", "explore"]' in autostarter_block


def test_saved_map_navigation_delays_optional_mission_services_until_nav_is_ready():
    launch_text = (PACKAGE_ROOT / "launch" / "ddsm_bringup.launch.py").read_text(
        encoding="utf-8"
    )

    assert '"mission_start_delay"' in launch_text
    assert 'default_value="150.0"' in launch_text
    assert "delayed_nav_mission_services = TimerAction(" in launch_text
    assert 'period=LaunchConfiguration("mission_start_delay")' in launch_text
    assert "home_manager," in launch_text
    assert "named_navigation_server," in launch_text
    assert "delayed_nav_mission_services," in launch_text


def test_saved_map_navigation_uses_custom_final_approach_without_unused_docking_server():
    launch_text = (PACKAGE_ROOT / "launch" / "ddsm_bringup.launch.py").read_text(
        encoding="utf-8"
    )
    saved_map_navigation_block = launch_text.split(
        "nav2_navigation = GroupAction", 1
    )[1].split("delayed_nav2_navigation = TimerAction", 1)[0]

    assert 'executable="opennav_docking"' not in saved_map_navigation_block
    assert '"docking_server"' not in saved_map_navigation_block
    assert 'executable="ddsm_final_approach_navigator"' in launch_text


def test_setup_installs_slam_lifecycle_autostarter_console_script():
    setup_text = (PACKAGE_ROOT / "setup.py").read_text(encoding="utf-8")

    assert (
        "slam_lifecycle_autostarter = "
        "ddsm_car_control.slam_lifecycle_autostarter:main"
    ) in setup_text
