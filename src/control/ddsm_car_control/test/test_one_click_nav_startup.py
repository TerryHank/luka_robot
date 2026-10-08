from pathlib import Path


WORKSPACE_ROOT = Path(__file__).resolve().parents[4]


def test_restart_nav_script_uses_current_nav_defaults_and_foxglove_bridge():
    script = (WORKSPACE_ROOT / "src/system/bringup/restart_nav_reset.sh").read_text(encoding="utf-8")

    assert "EKF_PARAMS_FILE" in script
    assert "ekf_imu_yaw_rate.yaml" in script
    assert "MAX_LINEAR_SPEED" in script
    assert "0.3" in script
    assert "foxglove_bridge" in script
    assert "foxglove_bridge_launch.xml" in script
    assert "ddsm_bringup.launch.py" in script
    assert "ddsm_home_manager" in script
    assert "explore_lite" in script
    assert "MODE=\"${MODE:-auto_nav}\"" in script
    assert "mode:='$MODE'" in script
    assert "setsid bash -lc" in script


def test_start_nav_with_foxglove_one_click_script_delegates_to_restart_script():
    script_path = WORKSPACE_ROOT / "src/visualization/console/start_nav_with_foxglove.sh"

    assert script_path.exists()
    assert script_path.stat().st_mode & 0o111
    script = script_path.read_text(encoding="utf-8")
    assert "RESTART_FOXGLOVE=1" in script
    assert "restart_nav_reset.sh" in script


def test_auto_nav_waits_for_delayed_navigation_lifecycle_startup():
    script = (WORKSPACE_ROOT / "src/system/bringup/restart_nav_reset.sh").read_text(encoding="utf-8")

    assert 'LOW_CPU_NAV="${LOW_CPU_NAV:-1}"' in script
    assert 'TIMEOUT="${TIMEOUT:-0.30}"' in script
    assert 'LIDAR_SCAN_FREQUENCY="${LIDAR_SCAN_FREQUENCY:-12.0}"' in script
    assert 'SCAN_PUBLISH_FREQUENCY="${SCAN_PUBLISH_FREQUENCY:-0.0}"' in script
    assert 'HEADING_PID_ENABLED="${HEADING_PID_ENABLED:-true}"' in script
    assert 'HEADING_PID_KP="${HEADING_PID_KP:-0.32}"' in script
    assert 'HEADING_PID_MAX_WZ="${HEADING_PID_MAX_WZ:-0.30}"' in script
    assert 'HEADING_HOLD_MIN_VX="${HEADING_HOLD_MIN_VX:-0.02}"' in script
    assert 'MECANUM_FORWARD_SCALE="${MECANUM_FORWARD_SCALE:-1.00}"' in script
    assert 'MECANUM_LATERAL_SCALE="${MECANUM_LATERAL_SCALE:-0.80}"' in script
    assert 'MECANUM_LATERAL_DIRECTION="${MECANUM_LATERAL_DIRECTION:-1}"' in script
    assert 'MECANUM_ANGULAR_SCALE="${MECANUM_ANGULAR_SCALE:-0.70}"' in script
    assert "heading_pid_enabled:='$HEADING_PID_ENABLED'" in script
    assert "heading_pid_kp:='$HEADING_PID_KP'" in script
    assert "heading_pid_max_wz:='$HEADING_PID_MAX_WZ'" in script
    assert "heading_hold_min_vx:='$HEADING_HOLD_MIN_VX'" in script
    assert "mecanum_forward_scale:='$MECANUM_FORWARD_SCALE'" in script
    assert "mecanum_lateral_scale:='$MECANUM_LATERAL_SCALE'" in script
    assert "mecanum_lateral_direction:='$MECANUM_LATERAL_DIRECTION'" in script
    assert "mecanum_angular_scale:='$MECANUM_ANGULAR_SCALE'" in script
    assert 'NAV_START_DELAY="${NAV_START_DELAY:-45.0}"' in script
    assert 'NAV_NODE_BATCH_DELAY="${NAV_NODE_BATCH_DELAY:-12.0}"' in script
    assert 'MISSION_START_DELAY="${MISSION_START_DELAY:-150.0}"' in script
    assert 'NAVIGATION_STARTUP_TIMEOUT="${NAVIGATION_STARTUP_TIMEOUT:-300}"' in script
    assert 'ENABLE_HOME_MANAGER="${ENABLE_HOME_MANAGER:-false}"' in script
    assert 'ENABLE_FINAL_APPROACH="${ENABLE_FINAL_APPROACH:-false}"' in script
    assert 'ENABLE_PATROL_MANAGER="${ENABLE_PATROL_MANAGER:-false}"' in script
    assert 'ENABLE_WATERPLUS_BRIDGE="${ENABLE_WATERPLUS_BRIDGE:-false}"' in script
    assert 'ENABLE_SEMANTIC_MAP="${ENABLE_SEMANTIC_MAP:-auto}"' in script
    assert 'ENABLE_NAMED_NAVIGATION="${ENABLE_NAMED_NAVIGATION:-auto}"' in script
    assert 'ENABLE_MISSION_CONTROL="${ENABLE_MISSION_CONTROL:-auto}"' in script
    assert 'ENABLE_MULTIFLOOR_MANAGER="${ENABLE_MULTIFLOOR_MANAGER:-false}"' in script
    assert "MULTIFLOOR_BUILDING_CONFIG_FILE" in script
    assert "MULTIFLOOR_STATE_FILE" in script
    assert "enable_mission_control:='$ENABLE_MISSION_CONTROL'" in script
    assert "enable_multifloor_manager:='$ENABLE_MULTIFLOOR_MANAGER'" in script
    assert (
        "multifloor_building_config_file:='$MULTIFLOOR_BUILDING_CONFIG_FILE'"
        in script
    )
    assert "multifloor_state_file:='$MULTIFLOOR_STATE_FILE'" in script
    assert "mission_state_file:='$MISSION_STATE_FILE'" in script
    assert "mission_zero_velocity_seconds:='$MISSION_ZERO_VELOCITY_SECONDS'" in script
    assert "mission_zero_velocity_hz:='$MISSION_ZERO_VELOCITY_HZ'" in script
    assert "low_cpu_nav:='$LOW_CPU_NAV'" in script
    assert "enable_home_manager:='$ENABLE_HOME_MANAGER'" in script
    assert "enable_final_approach:='$ENABLE_FINAL_APPROACH'" in script
    assert "enable_patrol_manager:='$ENABLE_PATROL_MANAGER'" in script
    assert "enable_semantic_map:='$ENABLE_SEMANTIC_MAP'" in script
    assert "enable_named_navigation:='$ENABLE_NAMED_NAVIGATION'" in script
    assert "nav_start_delay:='$NAV_START_DELAY'" in script
    assert "nav_node_batch_delay:='$NAV_NODE_BATCH_DELAY'" in script
    assert "mission_start_delay:='$MISSION_START_DELAY'" in script
    assert "lifecycle_manager_navigation_core.*Managed nodes are active" in script
    assert "lifecycle_manager_navigation_behavior.*Managed nodes are active" in script
    assert 'if [[ "$LOW_CPU_NAV" != "1" && "$LOW_CPU_NAV" != "true" && "$LOW_CPU_NAV" != "True" ]]' in script
    assert "lifecycle_manager_navigation_safety.*Managed nodes are active" in script
    assert "Named navigation ready" in script
    assert "if [[ \"$MODE\" == \"auto_nav\" ]]" in script


def test_explore_mode_uses_dedicated_low_load_params():
    script = (WORKSPACE_ROOT / "src/system/bringup/restart_nav_reset.sh").read_text(encoding="utf-8")

    assert 'if [[ "$MODE" == "explore" ]]' in script
    assert "ekf_explore.yaml" in script
    assert "nav2_explore_mppi_params.yaml" in script
    assert "SLAM_PARAMS_FILE" in script
    assert "slam_toolbox_mapping.yaml" in script


def test_failed_one_click_startup_cleans_only_its_launch_process_group():
    script = (WORKSPACE_ROOT / "src/system/bringup/restart_nav_reset.sh").read_text(encoding="utf-8")

    assert "cleanup_failed_start" in script
    assert "trap cleanup_failed_start EXIT" in script
    assert "ddsm_mission_control" in script
    assert "ddsm_multifloor_manager" in script
    assert 'kill -INT -- "-$pid"' in script
    assert "trap - EXIT" in script


def test_one_click_checks_live_lidar_before_stopping_navigation():
    script = (WORKSPACE_ROOT / "src/system/bringup/restart_nav_reset.sh").read_text(encoding="utf-8")

    assert 'KEEP_STACK_ON_LIDAR_FAILURE="${KEEP_STACK_ON_LIDAR_FAILURE:-false}"' in script
    assert "wait_for_live_scan_raw" in script
    assert "ensure_live_lidar" in script
    assert "PREFLIGHT_ONLY" in script
    assert 'setsid "$PERSISTENT_LIDAR_SCRIPT" 9>&-' in script
    assert script.index("if ! ensure_live_lidar; then") < script.index(
        "stop_robot_nav_stack", script.index("if ! ensure_live_lidar; then")
    )


def test_persistent_lidar_supervisor_reconnects_when_scan_data_stalls():
    script = (WORKSPACE_ROOT / "start_persistent_lidar.sh").read_text(
        encoding="utf-8"
    )

    assert "LIDAR_WATCHDOG_STARTUP_GRACE" in script
    assert "ros2 topic echo /scan_raw --once" in script
    assert "process is alive but /scan_raw has no data" in script
    assert "-p topic_name:=/scan_raw 8>&- &" in script
