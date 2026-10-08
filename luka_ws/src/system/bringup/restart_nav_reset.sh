#!/usr/bin/env bash
set -Eeuo pipefail

WS="${WS:-/home/sunrise/luka_ws}"
NAV_RMW_IMPLEMENTATION="${NAV_RMW_IMPLEMENTATION:-rmw_cyclonedds_cpp}"
NAV_CYCLONEDDS_URI="${NAV_CYCLONEDDS_URI:-file://$WS/src/common/config/cyclonedds_nav2.xml}"
TUNING_ENV_FILE="${TUNING_ENV_FILE:-$WS/src/common/config/runtime_tuning.env}"
USER_FEEDBACK_FREQ="${FEEDBACK_FREQ:-}"
if [[ -r "$TUNING_ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$TUNING_ENV_FILE"
  set +a
fi
if [[ -n "$USER_FEEDBACK_FREQ" ]]; then
  FEEDBACK_FREQ="$USER_FEEDBACK_FREQ"
fi
MODE="${MODE:-auto_nav}"
ACTIVE_FLOOR_CONTEXT_FILE="${ACTIVE_FLOOR_CONTEXT_FILE:-$WS/src/common/config/active_floor_context.json}"
if [[ -z "${MAP:-}" && -z "${FLOOR_ID:-}" && -r "$ACTIVE_FLOOR_CONTEXT_FILE" ]]; then
  mapfile -t active_floor_values < <(
    python3 -c 'import json,sys; data=json.load(open(sys.argv[1], encoding="utf-8")); print(data.get("floor_id", "")); print(data.get("map_file", ""))' \
      "$ACTIVE_FLOOR_CONTEXT_FILE" 2>/dev/null || true
  )
  if [[ -n "${active_floor_values[0]:-}" && -r "${active_floor_values[1]:-}" ]]; then
    FLOOR_ID="${active_floor_values[0]}"
    MAP="${active_floor_values[1]}"
  fi
fi
MAP="${MAP:-/home/sunrise/luka_data/maps/ddsm_map.yaml}"
FLOOR_ID="${FLOOR_ID:-}"
if [[ -z "$FLOOR_ID" ]]; then
  map_base="$(basename "$MAP")"
  if [[ "$map_base" =~ floor[_-]?([0-9]+) ]]; then
    FLOOR_ID="floor_${BASH_REMATCH[1]}"
  else
    FLOOR_ID="floor_1"
  fi
fi
ENABLE_DEPTH_CAMERA="${ENABLE_DEPTH_CAMERA:-false}"
ENABLE_COLORED_POINT_CLOUD="${ENABLE_COLORED_POINT_CLOUD:-false}"
ENABLE_DUAL_LIDAR="${ENABLE_DUAL_LIDAR:-true}"
ENABLE_DEPTH_OBSTACLE_FUSION="${ENABLE_DEPTH_OBSTACLE_FUSION:-false}"
LOW_LIDAR_IP="${LOW_LIDAR_IP:-192.168.11.2}"
LOW_LIDAR_PORT="${LOW_LIDAR_PORT:-8089}"
LOW_LIDAR_X="${LOW_LIDAR_X:-0.346}"
LOW_LIDAR_Y="${LOW_LIDAR_Y:-0.005}"
LOW_LIDAR_Z="${LOW_LIDAR_Z:-0.10}"
LOW_LIDAR_YAW="${LOW_LIDAR_YAW:-1.56975}"
LOW_LIDAR_INVERTED="${LOW_LIDAR_INVERTED:-true}"
LOW_LIDAR_KEEP_MIN_DEG="${LOW_LIDAR_KEEP_MIN_DEG:--180.0}"
LOW_LIDAR_KEEP_MAX_DEG="${LOW_LIDAR_KEEP_MAX_DEG:-0.0}"
ENABLE_SEMANTIC_MAPPING="${ENABLE_SEMANTIC_MAPPING:-false}"
SEMANTIC_FLOOR_ID="${SEMANTIC_FLOOR_ID:-$FLOOR_ID}"
SEMANTIC_OUTPUT_FILE="${SEMANTIC_OUTPUT_FILE:-$WS/src/common/config/semantic_auto/$SEMANTIC_FLOOR_ID/detections.yaml}"
export ENABLE_DEPTH_CAMERA ENABLE_COLORED_POINT_CLOUD ENABLE_SEMANTIC_MAPPING
export ENABLE_DUAL_LIDAR ENABLE_DEPTH_OBSTACLE_FUSION
export LOW_LIDAR_IP LOW_LIDAR_PORT LOW_LIDAR_X LOW_LIDAR_Y LOW_LIDAR_Z
export LOW_LIDAR_YAW LOW_LIDAR_INVERTED
export LOW_LIDAR_KEEP_MIN_DEG LOW_LIDAR_KEEP_MAX_DEG
export SEMANTIC_FLOOR_ID SEMANTIC_OUTPUT_FILE
mkdir -p "$(dirname "$SEMANTIC_OUTPUT_FILE")"
LASER_YAW="${LASER_YAW:-0.0}"
ENABLE_SCAN_DESKEW="${ENABLE_SCAN_DESKEW:-true}"
AMCL_TRANSFORM_TOLERANCE="${AMCL_TRANSFORM_TOLERANCE:-0.2}"
export ENABLE_SCAN_DESKEW AMCL_TRANSFORM_TOLERANCE
NAVIGATION_MOTION_MODE_FILE="${NAVIGATION_MOTION_MODE_FILE:-$WS/src/common/config/navigation_motion_mode.txt}"
if [[ -z "${NAVIGATION_MOTION_MODE:-}" && -r "$NAVIGATION_MOTION_MODE_FILE" ]]; then
  NAVIGATION_MOTION_MODE="$(tr -d '[:space:]' < "$NAVIGATION_MOTION_MODE_FILE")"
fi
NAVIGATION_MOTION_MODE="${NAVIGATION_MOTION_MODE:-omni}"
if [[ "$NAVIGATION_MOTION_MODE" != "omni" && "$NAVIGATION_MOTION_MODE" != "forward_facing" ]]; then
  echo "[restart_nav] warning: invalid navigation motion mode '$NAVIGATION_MOTION_MODE'; using omni"
  NAVIGATION_MOTION_MODE="omni"
fi
export NAVIGATION_MOTION_MODE
if [[ "$MODE" == "explore" ]]; then
  EKF_PARAMS_FILE="${EKF_PARAMS_FILE:-$WS/install/ddsm_car_control/share/ddsm_car_control/config/ekf_explore.yaml}"
  NAV_PARAMS_FILE="${NAV_PARAMS_FILE:-$WS/install/ddsm_car_control/share/ddsm_car_control/config/nav2_explore_mppi_params.yaml}"
  SLAM_PARAMS_FILE="${SLAM_PARAMS_FILE:-$WS/install/ddsm_car_control/share/ddsm_car_control/config/slam_toolbox_mapping.yaml}"
else
  EKF_PARAMS_FILE="${EKF_PARAMS_FILE:-$WS/install/ddsm_car_control/share/ddsm_car_control/config/ekf_imu_yaw_rate.yaml}"
  NAV_PARAMS_FILE="${NAV_PARAMS_FILE:-$WS/install/ddsm_car_control/share/ddsm_car_control/config/nav2_mecanum_mppi_params.yaml}"
  SLAM_PARAMS_FILE="${SLAM_PARAMS_FILE:-$WS/install/ddsm_car_control/share/ddsm_car_control/config/slam_toolbox_mapping.yaml}"
fi
MAX_LINEAR_SPEED="${MAX_LINEAR_SPEED:-1.8}"
MAX_ANGULAR_SPEED="${MAX_ANGULAR_SPEED:-9.0}"
MAX_MOTOR_RPM="${MAX_MOTOR_RPM:-300.0}"
CMD_FREQ="${CMD_FREQ:-50.0}"
TIMEOUT="${TIMEOUT:-0.30}"
LOW_CPU_NAV="${LOW_CPU_NAV:-1}"
FEEDBACK_ENABLED="${FEEDBACK_ENABLED:-true}"
READ_SPEED_FEEDBACK="${READ_SPEED_FEEDBACK:-false}"
FEEDBACK_FREQ="${FEEDBACK_FREQ:-30.0}"
FREE_ACK_WRITES="${FREE_ACK_WRITES:-true}"
SERIAL_TIMEOUT="${SERIAL_TIMEOUT:-0.03}"
IMU_PORT="${IMU_PORT:-/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0}"
if [[ "$MODE" == "explore" ]]; then
  LIDAR_SCAN_FREQUENCY="${LIDAR_SCAN_FREQUENCY:-10.0}"
  SCAN_PUBLISH_FREQUENCY="${SCAN_PUBLISH_FREQUENCY:-8.0}"
  MAP_PUBLISH_FREQUENCY="${MAP_PUBLISH_FREQUENCY:-8.0}"
  SLAM_MAP_UPDATE_INTERVAL="${SLAM_MAP_UPDATE_INTERVAL:-0.12}"
else
  LIDAR_SCAN_FREQUENCY="${LIDAR_SCAN_FREQUENCY:-12.0}"
  SCAN_PUBLISH_FREQUENCY="${SCAN_PUBLISH_FREQUENCY:-0.0}"
  MAP_PUBLISH_FREQUENCY="${MAP_PUBLISH_FREQUENCY:-12.0}"
  SLAM_MAP_UPDATE_INTERVAL="${SLAM_MAP_UPDATE_INTERVAL:-0.08}"
fi
IMU_HEADING_MODE="${IMU_HEADING_MODE:-relative}"
HEADING_PID_ENABLED="${HEADING_PID_ENABLED:-true}"
HEADING_PID_KP="${HEADING_PID_KP:-0.32}"
HEADING_PID_MAX_WZ="${HEADING_PID_MAX_WZ:-0.30}"
HEADING_HOLD_MIN_VX="${HEADING_HOLD_MIN_VX:-0.02}"
HEADING_HOLD_ANGULAR_DEADBAND="${HEADING_HOLD_ANGULAR_DEADBAND:-0.02}"
MECANUM_FORWARD_SCALE="${MECANUM_FORWARD_SCALE:-1.00}"
MECANUM_LATERAL_SCALE="${MECANUM_LATERAL_SCALE:-0.80}"
MECANUM_LATERAL_DIRECTION="${MECANUM_LATERAL_DIRECTION:-1}"
MECANUM_ANGULAR_SCALE="${MECANUM_ANGULAR_SCALE:-0.70}"
AUTO_LOCALIZER_LAST_POSE_FILE="${AUTO_LOCALIZER_LAST_POSE_FILE:-$WS/src/common/config/last_amcl_pose_${FLOOR_ID}.yaml}"
AUTO_LOCALIZER_ENABLE_ROTATION="${AUTO_LOCALIZER_ENABLE_ROTATION:-true}"
AUTO_LOCALIZER_MAX_ROTATION_SPEED="${AUTO_LOCALIZER_MAX_ROTATION_SPEED:-0.45}"
AUTO_LOCALIZER_ROTATION_CLEARANCE="${AUTO_LOCALIZER_ROTATION_CLEARANCE:-0.45}"
AUTO_LOCALIZER_ENABLE_ESCAPE="${AUTO_LOCALIZER_ENABLE_ESCAPE:-true}"
AUTO_LOCALIZER_ESCAPE_SPEED="${AUTO_LOCALIZER_ESCAPE_SPEED:-0.24}"
AUTO_LOCALIZER_ESCAPE_LATERAL_DIRECTION="${AUTO_LOCALIZER_ESCAPE_LATERAL_DIRECTION:-1.0}"
AUTO_LOCALIZER_ESCAPE_DURATION="${AUTO_LOCALIZER_ESCAPE_DURATION:-1.5}"
AUTO_LOCALIZER_ESCAPE_MAX_ATTEMPTS="${AUTO_LOCALIZER_ESCAPE_MAX_ATTEMPTS:-3}"
AUTO_LOCALIZER_WARM_START_TIMEOUT="${AUTO_LOCALIZER_WARM_START_TIMEOUT:-8.0}"
AUTO_LOCALIZER_GLOBAL_TIMEOUT="${AUTO_LOCALIZER_GLOBAL_TIMEOUT:-180.0}"
ENABLE_HOME_MANAGER="${ENABLE_HOME_MANAGER:-false}"
if [[ "$MODE" == "explore" ]]; then
  ENABLE_FINAL_APPROACH="${ENABLE_FINAL_APPROACH:-false}"
  ENABLE_PATROL_MANAGER="${ENABLE_PATROL_MANAGER:-false}"
else
  ENABLE_FINAL_APPROACH="${ENABLE_FINAL_APPROACH:-true}"
  ENABLE_PATROL_MANAGER="${ENABLE_PATROL_MANAGER:-true}"
fi
PATROL_ROUTE_FILE="${PATROL_ROUTE_FILE:-$WS/src/common/config/patrol_route_${FLOOR_ID}.yaml}"
if [[ ! -r "$PATROL_ROUTE_FILE" ]]; then
  PATROL_ROUTE_FILE="$WS/src/common/config/patrol_route.yaml"
fi
PATROL_REQUIRE_LOCALIZATION_READY="${PATROL_REQUIRE_LOCALIZATION_READY:-true}"
if [[ "$MODE" == "explore" ]]; then
  ENABLE_WATERPLUS_BRIDGE="${ENABLE_WATERPLUS_BRIDGE:-false}"
else
  ENABLE_WATERPLUS_BRIDGE="${ENABLE_WATERPLUS_BRIDGE:-true}"
fi
WATERPLUS_WAYPOINTS_FILE="${WATERPLUS_WAYPOINTS_FILE:-$WS/src/common/config/waypoints_${FLOOR_ID}.xml}"
if [[ ! -r "$WATERPLUS_WAYPOINTS_FILE" ]]; then
  WATERPLUS_WAYPOINTS_FILE="$WS/src/common/config/waypoints.xml"
fi
WATERPLUS_DEFAULT_WAYPOINT_TYPE="${WATERPLUS_DEFAULT_WAYPOINT_TYPE:-stop}"
WATERPLUS_DEFAULT_FINAL_APPROACH="${WATERPLUS_DEFAULT_FINAL_APPROACH:-false}"
ENABLE_WATERPLUS_GOAL_POSE_ALIAS="${ENABLE_WATERPLUS_GOAL_POSE_ALIAS:-true}"
WATERPLUS_GOAL_POSE_TOPIC="${WATERPLUS_GOAL_POSE_TOPIC:-/goal_pose}"
NAV2_GOAL_POSE_TOPIC="${NAV2_GOAL_POSE_TOPIC:-/nav_goal_pose}"
FINAL_APPROACH_GOAL_TOPIC="${FINAL_APPROACH_GOAL_TOPIC:-/final_approach/goal_pose}"
ENABLE_LATERAL_ESCAPE_GUARD="${ENABLE_LATERAL_ESCAPE_GUARD:-auto}"
NAV_CONTROLLER_CMD_VEL_TOPIC="${NAV_CONTROLLER_CMD_VEL_TOPIC:-/cmd_vel_nav_raw}"
LATERAL_ESCAPE_DIRECTION_SIGN="${LATERAL_ESCAPE_DIRECTION_SIGN:-1.0}"
if [[ "$MODE" == "explore" ]]; then
  ENABLE_SEMANTIC_MAP="${ENABLE_SEMANTIC_MAP:-false}"
  ENABLE_NAMED_NAVIGATION="${ENABLE_NAMED_NAVIGATION:-false}"
  ENABLE_MISSION_CONTROL="${ENABLE_MISSION_CONTROL:-false}"
else
  ENABLE_SEMANTIC_MAP="${ENABLE_SEMANTIC_MAP:-auto}"
  ENABLE_NAMED_NAVIGATION="${ENABLE_NAMED_NAVIGATION:-auto}"
  ENABLE_MISSION_CONTROL="${ENABLE_MISSION_CONTROL:-auto}"
fi

if [[ "$MODE" == "explore" ]]; then
  MAX_LINEAR_SPEED="${EXPLORE_MAX_LINEAR_SPEED:-0.18}"
  MAX_ANGULAR_SPEED="${EXPLORE_MAX_ANGULAR_SPEED:-0.60}"
  LIDAR_SCAN_FREQUENCY="${EXPLORE_LIDAR_SCAN_FREQUENCY:-6.0}"
  SCAN_PUBLISH_FREQUENCY="${EXPLORE_SCAN_PUBLISH_FREQUENCY:-0.0}"
  MAP_PUBLISH_FREQUENCY="${EXPLORE_MAP_PUBLISH_FREQUENCY:-3.0}"
  SLAM_MAP_UPDATE_INTERVAL="${EXPLORE_SLAM_MAP_UPDATE_INTERVAL:-0.25}"
fi
SEMANTIC_MAP_MANIFEST="${SEMANTIC_MAP_MANIFEST:-$WS/src/common/config/semantic/${FLOOR_ID}/map_manifest.yaml}"
if [[ ! -r "$SEMANTIC_MAP_MANIFEST" ]]; then
  SEMANTIC_MAP_MANIFEST="$WS/install/hotel_semantic_map/share/hotel_semantic_map/config/map_manifest.yaml"
fi
MISSION_STATE_FILE="${MISSION_STATE_FILE:-$WS/src/common/config/mission_state_${FLOOR_ID}.yaml}"
MISSION_ZERO_VELOCITY_SECONDS="${MISSION_ZERO_VELOCITY_SECONDS:-1.0}"
MISSION_ZERO_VELOCITY_HZ="${MISSION_ZERO_VELOCITY_HZ:-30.0}"
ENABLE_MULTIFLOOR_MANAGER="${ENABLE_MULTIFLOOR_MANAGER:-false}"
ENABLE_ELEVATOR_ADAPTER="${ENABLE_ELEVATOR_ADAPTER:-true}"
ENABLE_ELEVATOR_ENTRY_CONTROLLER="${ENABLE_ELEVATOR_ENTRY_CONTROLLER:-true}"
ELEVATOR_ENTRY_PARAMS_FILE="${ELEVATOR_ENTRY_PARAMS_FILE:-$WS/install/ddsm_car_control/share/ddsm_car_control/config/elevator_entry_v1.yaml}"
MULTIFLOOR_BUILDING_CONFIG_FILE="${MULTIFLOOR_BUILDING_CONFIG_FILE:-$WS/src/common/config/multifloor_building.yaml}"
MULTIFLOOR_STATE_FILE="${MULTIFLOOR_STATE_FILE:-$WS/src/common/config/floor_mission_state.yaml}"
MULTIFLOOR_CURRENT_FLOOR_ID="${MULTIFLOOR_CURRENT_FLOOR_ID:-$FLOOR_ID}"
LIFECYCLE_BOND_TIMEOUT="${LIFECYCLE_BOND_TIMEOUT:-180.0}"
LIFECYCLE_STARTUP_TIMEOUT="${LIFECYCLE_STARTUP_TIMEOUT:-240}"
LIFECYCLE_STABILITY_WINDOW="${LIFECYCLE_STABILITY_WINDOW:-15}"
LIDAR_READY_TIMEOUT="${LIDAR_READY_TIMEOUT:-20}"
LIDAR_STARTUP_RETRIES="${LIDAR_STARTUP_RETRIES:-3}"
LIDAR_RETRY_DELAY="${LIDAR_RETRY_DELAY:-3}"
LIDAR_PREFLIGHT_TIMEOUT="${LIDAR_PREFLIGHT_TIMEOUT:-18}"
KEEP_STACK_ON_LIDAR_FAILURE="${KEEP_STACK_ON_LIDAR_FAILURE:-false}"
START_LIDAR_DRIVER="${START_LIDAR_DRIVER:-false}"
PERSISTENT_LIDAR_SCRIPT="${PERSISTENT_LIDAR_SCRIPT:-$WS/src/system/bringup/start_persistent_lidar.sh}"
export START_LIDAR_DRIVER
NAV_START_DELAY="${NAV_START_DELAY:-45.0}"
NAV_NODE_BATCH_DELAY="${NAV_NODE_BATCH_DELAY:-12.0}"
MISSION_START_DELAY="${MISSION_START_DELAY:-150.0}"
NAVIGATION_STARTUP_TIMEOUT="${NAVIGATION_STARTUP_TIMEOUT:-300}"
MISSION_STARTUP_TIMEOUT="${MISSION_STARTUP_TIMEOUT:-240}"
USE_RESPAWN="${USE_RESPAWN:-False}"
RESTART_FOXGLOVE="${RESTART_FOXGLOVE:-1}"
FOXGLOVE_HOST="${FOXGLOVE_HOST:-192.168.3.150}"
FOXGLOVE_PORT="${FOXGLOVE_PORT:-8765}"
FOXGLOVE_THREADS="${FOXGLOVE_THREADS:-4}"
LOG_DIR="$WS/log/codex"

mkdir -p "$LOG_DIR"

RESTART_LOCK_FILE="$LOG_DIR/restart_nav_reset.lock"
exec 9>"$RESTART_LOCK_FILE"
if ! flock -n 9; then
  echo "[restart_nav] another startup is already in progress; ignoring duplicate request"
  exit 75
fi

wait_for_foxglove() {
  local old_pid="${1:-}"
  local state=""
  local main_pid=""
  local listening=""

  for _ in {1..30}; do
    state="$(systemctl is-active foxglove-bridge.service 2>/dev/null || true)"
    main_pid="$(systemctl show foxglove-bridge.service -p MainPID --value 2>/dev/null || true)"
    listening="$(ss -ltn 2>/dev/null | awk -v port=":${FOXGLOVE_PORT}" '$4 ~ port {print $4; exit}')"
    if [[ -n "$listening" ]]; then
      if [[ -z "$old_pid" || -z "$main_pid" || "$main_pid" == "0" || "$main_pid" != "$old_pid" ]]; then
        echo "[restart_nav] foxglove_bridge ready pid=${main_pid:-manual} listen=$listening url=ws://${FOXGLOVE_HOST}:${FOXGLOVE_PORT}"
        return 0
      fi
    fi
    sleep 1
  done

  echo "[restart_nav] warning: foxglove_bridge not fully ready"
  echo "[restart_nav] foxglove_bridge state=$(systemctl is-active foxglove-bridge.service 2>/dev/null || true)"
  echo "[restart_nav] foxglove_bridge pid=$(systemctl show foxglove-bridge.service -p MainPID --value 2>/dev/null || true)"
  ss -ltnp 2>/dev/null | grep ":${FOXGLOVE_PORT}" || true
  return 1
}

restart_foxglove_bridge() {
  local old_pid=""
  local fox_log="$LOG_DIR/foxglove_bridge_$(date +%Y%m%d_%H%M%S).log"

  old_pid="$(systemctl show foxglove-bridge.service -p MainPID --value 2>/dev/null || true)"
  echo "[restart_nav] restarting foxglove_bridge old_pid=${old_pid:-none}"

  if systemctl cat foxglove-bridge.service >/dev/null 2>&1; then
    if systemctl restart foxglove-bridge.service >/dev/null 2>&1; then
      wait_for_foxglove "$old_pid" && return 0
    else
      echo "[restart_nav] systemctl restart failed; trying process restart fallback"
      if [[ -n "$old_pid" && "$old_pid" != "0" ]]; then
        kill -TERM "$old_pid" 2>/dev/null || true
      fi
      systemctl start foxglove-bridge.service >/dev/null 2>&1 || true
      wait_for_foxglove "$old_pid" && return 0
    fi
  fi

  echo "[restart_nav] starting foxglove_bridge manually log=$fox_log"
  pkill -TERM -f 'foxglove_bridge_launch.xml|/foxglove_bridge/foxglove_bridge' 2>/dev/null || true
  sleep 2
  pkill -KILL -f 'foxglove_bridge_launch.xml|/foxglove_bridge/foxglove_bridge' 2>/dev/null || true

  setsid bash -lc "
    unset ROS_LOCALHOST_ONLY
    export ROS_AUTOMATIC_DISCOVERY_RANGE='${ROS_AUTOMATIC_DISCOVERY_RANGE:-SUBNET}'
    export FASTDDS_BUILTIN_TRANSPORTS='${FASTDDS_BUILTIN_TRANSPORTS:-UDPv4}'
    export RMW_IMPLEMENTATION='rmw_fastrtps_cpp'
    unset CYCLONEDDS_URI
    set +u
    source /opt/ros/humble/setup.bash
    source '$WS/install/setup.bash'
    set -u
    exec ros2 launch foxglove_bridge foxglove_bridge_launch.xml address:=0.0.0.0 port:='$FOXGLOVE_PORT' num_threads:='$FOXGLOVE_THREADS'
  " > "$fox_log" 2>&1 < /dev/null &

  wait_for_foxglove "" || true
}

ensure_foxglove_map_delivery() {
  local map_qos=""

  case "$RESTART_FOXGLOVE" in
    1|true|True|TRUE|yes|Yes|YES)
      ;;
    *)
      echo "[restart_nav] RESTART_FOXGLOVE=0; leaving foxglove_bridge untouched"
      return 0
      ;;
  esac

  if ! ss -ltn 2>/dev/null | grep -q ":${FOXGLOVE_PORT}"; then
    return 0
  fi

  map_qos="$(
    ros2 topic info -v /map 2>/dev/null \
      | awk '
          /Node name: foxglove_bridge/ {capture=1}
          capture {print}
          capture && /Liveliness lease duration:/ {exit}
        ' || true
  )"
  if [[ -z "$map_qos" ]]; then
    return 0
  fi
  if grep -q "Reliability: RELIABLE" <<<"$map_qos" \
    && grep -q "Durability: TRANSIENT_LOCAL" <<<"$map_qos"; then
    echo "[restart_nav] Foxglove /map QoS is compatible"
    return 0
  fi

  echo "[restart_nav] Foxglove /map QoS is stale; refreshing bridge after map activation"
  restart_foxglove_bridge
}

stop_robot_nav_stack() {
  echo "[restart_nav] stopping robot-side navigation stack"
  # Following must never survive a navigation-stack teardown and resume using
  # old state. Start its idle service only after the new stack is ready.
  if ! XDG_RUNTIME_DIR=/run/user/1000 systemctl --user stop person-follow.service; then
    echo "[restart_nav] error: cannot stop person-follow.service; aborting teardown"
    return 1
  fi
  python3 - <<'PY'
import os
import signal
import subprocess
import time

patterns = [
    'ros2 launch ddsm_car_control ddsm_bringup.launch.py',
    'ros2 launch ddsm_car_control ddsm_car.launch.py',
    'ros2 launch ddsm_car_control ddsm_robot_bringup.launch.py',
    'ros2 launch ddsm_car_control ddsm_slam.launch.py',
    'ros2 launch ddsm_car_control ddsm_nav2.launch.py',
    '/opt/ros/humble/lib/nav2_map_server/map_saver_server',
    '/home/sunrise/luka_ws/install/ddsm_car_control/lib/ddsm_car_control/udp_cmd_vel_bridge',
    '/home/sunrise/luka_ws/install/ddsm_car_control/lib/ddsm_car_control/zdt_mecanum_rs485_bridge',
    '/home/sunrise/luka_ws/install/ddsm_car_control/lib/ddsm_car_control/cmd_vel_to_ddsm',
    '/home/sunrise/luka_ws/install/ddsm_car_control/lib/ddsm_car_control/encoder_logger',
    '/home/sunrise/luka_ws/install/ddsm_car_control/lib/ddsm_car_control/wit_imu_node',
    '/home/sunrise/luka_ws/install/ddsm_car_control/lib/ddsm_car_control/map_republisher',
    '/home/sunrise/luka_ws/install/ddsm_car_control/lib/ddsm_car_control/scan_throttler',
    '/home/sunrise/luka_ws/install/ddsm_car_control/lib/ddsm_car_control/laser_scan_deskewer',
    '/home/sunrise/luka_ws/install/ddsm_car_control/lib/ddsm_car_control/low_lidar_udp_proxy',
    '/home/sunrise/luka_ws/install/rplidar_ros/lib/rplidar_ros/rplidar_node --ros-args -r __node:=rplidar_low_node',
    '/home/sunrise/luka_ws/install/ddsm_car_control/lib/ddsm_car_control/dual_laser_fusion',
    '/home/sunrise/luka_ws/install/ddsm_car_control/lib/ddsm_car_control/depth_obstacle_monitor',
    '/opt/ros/humble/lib/topic_tools/throttle messages',
    '/home/sunrise/luka_ws/install/ddsm_car_control/lib/ddsm_car_control/colored_point_cloud_relay',
    '/home/sunrise/luka_ws/install/ddsm_car_control/lib/ddsm_car_control/semantic_mapping_recorder',
    '/opt/ros/humble/lib/robot_localization/ekf_node',
    '/home/sunrise/luka_ws/install/orbbec_camera/lib/orbbec_camera/orbbec_camera_node',
    '/opt/ros/humble/lib/tf2_ros/static_transform_publisher',
    '/opt/ros/humble/lib/robot_state_publisher/robot_state_publisher',
    '/opt/ros/humble/lib/slam_toolbox/async_slam_toolbox_node',
    '/opt/ros/humble/lib/slam_toolbox/sync_slam_toolbox_node',
    '/opt/ros/humble/lib/slam_toolbox/',
    '/opt/ros/humble/lib/nav2_map_server/map_server',
    '/opt/ros/humble/lib/nav2_amcl/amcl',
    '/opt/ros/humble/lib/nav2_controller/controller_server',
    '/opt/ros/humble/lib/nav2_planner/planner_server',
    '/opt/ros/humble/lib/nav2_behaviors/behavior_server',
    '/opt/ros/humble/lib/nav2_bt_navigator/bt_navigator',
    '/opt/ros/humble/lib/nav2_waypoint_follower/waypoint_follower',
    '/opt/ros/humble/lib/nav2_velocity_smoother/velocity_smoother',
    '/opt/ros/humble/lib/nav2_smoother/smoother_server',
    '/opt/ros/humble/lib/nav2_route/route_server',
    '/opt/ros/humble/lib/opennav_docking/opennav_docking',
    '/opt/ros/humble/lib/nav2_collision_monitor/collision_monitor',
    '/opt/ros/humble/lib/nav2_lifecycle_manager/lifecycle_manager',
    '/opt/ros/humble/lib/rclcpp_components/component_container_isolated',
    '/home/sunrise/luka_ws/install/ddsm_car_control/lib/ddsm_car_control/ddsm_home_manager',
    '/home/sunrise/luka_ws/install/ddsm_car_control/lib/ddsm_car_control/ddsm_final_approach_navigator',
    '/home/sunrise/luka_ws/install/ddsm_car_control/lib/ddsm_car_control/ddsm_auto_localizer',
    '/home/sunrise/luka_ws/install/ddsm_car_control/lib/ddsm_car_control/ddsm_patrol_manager',
    '/home/sunrise/luka_ws/install/ddsm_car_control/lib/ddsm_car_control/ddsm_waterplus_bridge',
    '/home/sunrise/luka_ws/install/ddsm_car_control/lib/ddsm_car_control/ddsm_mission_control',
    '/home/sunrise/luka_ws/install/ddsm_car_control/lib/ddsm_car_control/ddsm_multifloor_manager',
    '/home/sunrise/luka_ws/install/ddsm_car_control/lib/ddsm_car_control/ddsm_elevator_adapter',
    '/home/sunrise/luka_ws/install/ddsm_car_control/lib/ddsm_car_control/elevator_entry_controller',
    '/home/sunrise/luka_ws/install/ddsm_car_control/lib/ddsm_car_control/ddsm_lateral_escape_guard',
    '/home/sunrise/luka_ws/install/hotel_semantic_map/lib/hotel_semantic_map/semantic_map_server',
    '/home/sunrise/luka_ws/install/hotel_semantic_map/lib/hotel_semantic_map/named_navigation_server',
    '/home/sunrise/luka_ws/install/nav_llm_agent/lib/nav_llm_agent/agent_node',
    'ddsm_auto_localizer',
    'ddsm_patrol_manager',
    'ddsm_waterplus_bridge',
    'ddsm_mission_control',
    'ddsm_multifloor_manager',
    'ddsm_elevator_adapter',
    'elevator_entry_controller',
    'ddsm_final_approach_navigator',
    'ddsm_lateral_escape_guard',
    'nav_llm_agent agent_node',
    '/home/sunrise/luka_ws/install/explore_lite/lib/explore_lite/explore',
    'explore_node',
    'nav_lifecycle_autostarter',
    'slam_lifecycle_autostarter',
]


def candidates():
    out = subprocess.check_output(['ps', '-eo', 'pid=,ppid=,cmd='], text=True, errors='replace')
    rows = []
    me = os.getpid()
    for line in out.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) < 3:
            continue
        pid, ppid, cmd = int(parts[0]), int(parts[1]), parts[2]
        if pid == me:
            continue
        if 'foxglove_bridge' in cmd or 'foxglove_bridge_launch' in cmd:
            continue
        if any(pattern in cmd for pattern in patterns):
            rows.append((pid, ppid, cmd))
    return rows


for sig, delay in [(signal.SIGINT, 5), (signal.SIGTERM, 3), (signal.SIGKILL, 1)]:
    rows = candidates()
    if not rows:
        break
    print(f"[restart_nav] signal {sig.name}: " + " ".join(str(row[0]) for row in rows))
    for pid, _, _ in rows:
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            pass
    time.sleep(delay)

remaining = candidates()
if remaining:
    print("[restart_nav] warning: remaining robot-side processes:")
    for pid, ppid, cmd in remaining:
        print(f"  {pid} {ppid} {cmd}")
PY
}

set +u
source /opt/ros/humble/setup.bash
source "$WS/install/setup.bash"
set -u

unset ROS_LOCALHOST_ONLY
export ROS_AUTOMATIC_DISCOVERY_RANGE="${ROS_AUTOMATIC_DISCOVERY_RANGE:-SUBNET}"
export FASTDDS_BUILTIN_TRANSPORTS="${FASTDDS_BUILTIN_TRANSPORTS:-UDPv4}"
export RMW_IMPLEMENTATION="$NAV_RMW_IMPLEMENTATION"
export CYCLONEDDS_URI="$NAV_CYCLONEDDS_URI"

ensure_persistent_lidar() {
  local supervisor_pid=""
  local lidar_pidfile="$LOG_DIR/persistent_lidar.pid"

  if [[ -r "$lidar_pidfile" ]]; then
    supervisor_pid="$(cat "$lidar_pidfile" 2>/dev/null || true)"
  fi
  if [[ -n "$supervisor_pid" ]] \
    && { ! [[ "$supervisor_pid" =~ ^[0-9]+$ ]] \
      || ! kill -0 "$supervisor_pid" 2>/dev/null \
      || ! ps -p "$supervisor_pid" -o args= 2>/dev/null | grep -Fq "$PERSISTENT_LIDAR_SCRIPT"; }; then
    supervisor_pid=""
  fi
  if [[ -z "$supervisor_pid" ]]; then
    supervisor_pid="$(pgrep -o -f "^bash $PERSISTENT_LIDAR_SCRIPT$" 2>/dev/null || true)"
    if [[ -n "$supervisor_pid" ]]; then
      echo "$supervisor_pid" > "$lidar_pidfile"
    fi
  fi
  if [[ -n "$supervisor_pid" ]] && kill -0 "$supervisor_pid" 2>/dev/null; then
    echo "[restart_nav] persistent lidar supervisor already running pid=$supervisor_pid"
    return 0
  fi
  if [[ ! -x "$PERSISTENT_LIDAR_SCRIPT" ]]; then
    echo "[restart_nav] error: persistent lidar script is missing: $PERSISTENT_LIDAR_SCRIPT"
    return 1
  fi

  echo "[restart_nav] starting persistent lidar supervisor"
  setsid "$PERSISTENT_LIDAR_SCRIPT" 9>&- > "$LOG_DIR/persistent_lidar_supervisor.log" 2>&1 < /dev/null &
  supervisor_pid="$!"
  echo "$supervisor_pid" > "$lidar_pidfile"
  sleep 2
  if ! kill -0 "$supervisor_pid" 2>/dev/null; then
    echo "[restart_nav] error: persistent lidar supervisor exited during startup"
    tail -n 40 "$LOG_DIR/persistent_lidar_supervisor.log" || true
    return 1
  fi
  echo "[restart_nav] persistent lidar supervisor ready pid=$supervisor_pid"
}

wait_for_live_scan_raw() {
  local timeout_seconds="$1"
  local deadline=$((SECONDS + timeout_seconds))

  while (( SECONDS < deadline )); do
    if timeout 5 ros2 topic echo /scan_raw --once \
      --field header.stamp.sec \
      --qos-reliability best_effort >/dev/null 2>&1; then
      echo "[restart_nav] live /scan_raw data is ready"
      return 0
    fi
    sleep 1
  done
  return 1
}

restart_persistent_lidar() {
  local supervisor_pid=""
  local lidar_pidfile="$LOG_DIR/persistent_lidar.pid"

  if [[ -r "$lidar_pidfile" ]]; then
    supervisor_pid="$(cat "$lidar_pidfile" 2>/dev/null || true)"
  fi
  if [[ "$supervisor_pid" =~ ^[0-9]+$ ]] && kill -0 "$supervisor_pid" 2>/dev/null; then
    echo "[restart_nav] restarting stale persistent lidar supervisor pid=$supervisor_pid"
    kill -TERM "$supervisor_pid" 2>/dev/null || true
    for _ in {1..8}; do
      kill -0 "$supervisor_pid" 2>/dev/null || break
      sleep 1
    done
    if kill -0 "$supervisor_pid" 2>/dev/null; then
      echo "[restart_nav] error: stale lidar supervisor did not stop"
      return 1
    fi
  fi
  rm -f "$lidar_pidfile"
  ensure_persistent_lidar
}

ensure_live_lidar() {
  ensure_persistent_lidar
  echo "[restart_nav] checking real lidar data before changing navigation"
  if wait_for_live_scan_raw 8; then
    return 0
  fi

  echo "[restart_nav] no live /scan_raw; attempting one automatic lidar reconnect"
  restart_persistent_lidar
  if wait_for_live_scan_raw "$LIDAR_PREFLIGHT_TIMEOUT"; then
    return 0
  fi

  echo "[restart_nav] error: radar process exists but /scan_raw has no live data"
  if ! ping -c 1 -W 1 192.168.11.2 >/dev/null 2>&1; then
    echo "[restart_nav] error: S2E 192.168.11.2 is unreachable; power-cycle the radar and S2E converter"
  fi
  return 1
}

if [[ "${STOP_ONLY:-0}" == "1" || "${STOP_ONLY:-0}" == "true" || "${STOP_ONLY:-0}" == "True" ]]; then
  stop_robot_nav_stack
  echo "[restart_nav] robot-side stack stopped; Foxglove Bridge was preserved"
  exit 0
fi

if ! ensure_live_lidar; then
  echo "[restart_nav] startup blocked before stopping the existing navigation stack"
  exit 1
fi

if [[ "${PREFLIGHT_ONLY:-0}" == "1" || "${PREFLIGHT_ONLY:-0}" == "true" || "${PREFLIGHT_ONLY:-0}" == "True" ]]; then
  echo "[restart_nav] lidar preflight passed"
  exit 0
fi

stop_robot_nav_stack

wait_for_log_pattern() {
  local pattern="$1"
  local label="$2"
  local timeout_seconds="$3"
  local deadline=$((SECONDS + timeout_seconds))

  echo "[restart_nav] waiting for $label (timeout=${timeout_seconds}s)"
  while (( SECONDS < deadline )); do
    if grep -Eq "$pattern" "$log" 2>/dev/null; then
      echo "[restart_nav] $label is ready"
      return 0
    fi
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "[restart_nav] error: launch process exited before $label became ready"
      return 1
    fi
    sleep 2
  done

  echo "[restart_nav] error: timed out waiting for $label"
  return 1
}

lifecycle_node_is_active() {
  local node_name="$1"
  timeout 4 ros2 lifecycle get "$node_name" 2>/dev/null \
    | grep -Eq '^active \[3\]$'
}

wait_for_localization_runtime_health() {
  local timeout_seconds="$1"
  local deadline=$((SECONDS + timeout_seconds))

  echo "[restart_nav] verifying live localization lifecycle state"
  while (( SECONDS < deadline )); do
    if lifecycle_node_is_active /map_server \
      && lifecycle_node_is_active /amcl; then
      if timeout 8 ros2 topic echo /map --once \
        --qos-reliability reliable \
        --qos-durability transient_local \
        --field info.width 2>/dev/null | grep -Eq '[1-9][0-9]*'; then
        echo "[restart_nav] live localization is healthy: map_server=active amcl=active /map=ready"
        return 0
      fi
    fi
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "[restart_nav] error: launch exited during live localization verification"
      return 1
    fi
    sleep 2
  done

  echo "[restart_nav] error: live localization health check timed out"
  timeout 4 ros2 lifecycle get /map_server 2>/dev/null || true
  timeout 4 ros2 lifecycle get /amcl 2>/dev/null || true
  return 1
}

wait_for_map_laser_transform() {
  local timeout_seconds="$1"
  local deadline=$((SECONDS + timeout_seconds))
  local scan_frame=""
  local scan_message=""
  local tf_output=""

  echo "[restart_nav] waiting for live map->scan transform"
  while (( SECONDS < deadline )); do
    if [[ -z "$scan_frame" ]]; then
      scan_message="$(timeout 5 ros2 topic echo --once /scan 2>/dev/null || true)"
      scan_frame="$(awk -F': ' '/^[[:space:]]*frame_id:/{gsub(/[[:space:]\x27\x22]/, "", $2); print $2; exit}' <<<"$scan_message")"
      if [[ -n "$scan_frame" ]]; then
        echo "[restart_nav] detected /scan frame_id=$scan_frame"
      fi
    fi

    if [[ -n "$scan_frame" ]]; then
      tf_output="$(timeout 5 ros2 run tf2_ros tf2_echo map "$scan_frame" 2>/dev/null || true)"
    else
      tf_output=""
    fi
    if grep -q 'Translation:' <<<"$tf_output"; then
      echo "[restart_nav] map->$scan_frame transform is ready"
      return 0
    fi
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "[restart_nav] error: launch exited before map->scan became ready"
      return 1
    fi
    sleep 2
  done

  echo "[restart_nav] error: timed out waiting for map->scan frame=${scan_frame:-unknown}"
  return 1
}

wait_for_map_laser_with_retries() {
  local attempt
  for ((attempt=1; attempt<=LIDAR_STARTUP_RETRIES; attempt++)); do
    echo "[restart_nav] lidar readiness attempt $attempt/$LIDAR_STARTUP_RETRIES"
    if wait_for_map_laser_transform "$LIDAR_READY_TIMEOUT"; then
      return 0
    fi
    if ! kill -0 "$pid" 2>/dev/null; then
      return 1
    fi
    if (( attempt < LIDAR_STARTUP_RETRIES )); then
      sleep "$LIDAR_RETRY_DELAY"
    fi
  done
  return 1
}

pid=""
cleanup_failed_start() {
  local status=$?
  trap - EXIT
  if (( status != 0 )) && [[ -n "${pid:-}" ]] && kill -0 "$pid" 2>/dev/null; then
    echo "[restart_nav] startup failed; stopping launch process group $pid"
    kill -INT -- "-$pid" 2>/dev/null || true
    for _ in {1..10}; do
      kill -0 "$pid" 2>/dev/null || break
      sleep 1
    done
    if kill -0 "$pid" 2>/dev/null; then
      kill -TERM -- "-$pid" 2>/dev/null || true
      sleep 3
    fi
    if kill -0 "$pid" 2>/dev/null; then
      kill -KILL -- "-$pid" 2>/dev/null || true
    fi
  fi
  exit "$status"
}
trap cleanup_failed_start EXIT

if [[ "$RESTART_FOXGLOVE" == "1" || "$RESTART_FOXGLOVE" == "true" || "$RESTART_FOXGLOVE" == "True" ]]; then
  restart_foxglove_bridge
else
  wait_for_foxglove "" || true
fi

stamp="$(date +%Y%m%d_%H%M%S)"
log="$LOG_DIR/nav_reset_${stamp}.log"
pidfile="$LOG_DIR/nav_clean.pid"

echo "[restart_nav] starting mode=$MODE"
echo "[restart_nav] map=$MAP"
echo "[restart_nav] floor_id=$FLOOR_ID"
echo "[restart_nav] enable_depth_camera=$ENABLE_DEPTH_CAMERA enable_semantic_mapping=$ENABLE_SEMANTIC_MAPPING semantic_floor_id=$SEMANTIC_FLOOR_ID semantic_output_file=$SEMANTIC_OUTPUT_FILE"
echo "[restart_nav] enable_dual_lidar=$ENABLE_DUAL_LIDAR enable_depth_obstacle_fusion=$ENABLE_DEPTH_OBSTACLE_FUSION low_lidar=${LOW_LIDAR_IP}:${LOW_LIDAR_PORT} pose=(${LOW_LIDAR_X},${LOW_LIDAR_Y},${LOW_LIDAR_Z},${LOW_LIDAR_YAW}) keep_deg=(${LOW_LIDAR_KEEP_MIN_DEG},${LOW_LIDAR_KEEP_MAX_DEG}) inverted=$LOW_LIDAR_INVERTED"
echo "[restart_nav] ekf_params_file=$EKF_PARAMS_FILE"
echo "[restart_nav] nav_params_file=$NAV_PARAMS_FILE"
echo "[restart_nav] slam_params_file=$SLAM_PARAMS_FILE"
echo "[restart_nav] enable_scan_deskew=$ENABLE_SCAN_DESKEW amcl_transform_tolerance=$AMCL_TRANSFORM_TOLERANCE"
echo "[restart_nav] navigation_motion_mode=$NAVIGATION_MOTION_MODE"
echo "[restart_nav] max_linear_speed=$MAX_LINEAR_SPEED max_angular_speed=$MAX_ANGULAR_SPEED max_motor_rpm=$MAX_MOTOR_RPM cmd_freq=$CMD_FREQ timeout=$TIMEOUT low_cpu_nav=$LOW_CPU_NAV feedback_enabled=$FEEDBACK_ENABLED read_speed_feedback=$READ_SPEED_FEEDBACK feedback_freq=$FEEDBACK_FREQ free_ack_writes=$FREE_ACK_WRITES serial_timeout=$SERIAL_TIMEOUT imu_port=$IMU_PORT lidar_scan_frequency=$LIDAR_SCAN_FREQUENCY scan_publish_frequency=$SCAN_PUBLISH_FREQUENCY map_publish_frequency=$MAP_PUBLISH_FREQUENCY slam_map_update_interval=$SLAM_MAP_UPDATE_INTERVAL laser_yaw=$LASER_YAW imu_heading_mode=$IMU_HEADING_MODE"
echo "[restart_nav] heading_pid_enabled=$HEADING_PID_ENABLED heading_pid_kp=$HEADING_PID_KP heading_pid_max_wz=$HEADING_PID_MAX_WZ heading_hold_min_vx=$HEADING_HOLD_MIN_VX heading_hold_angular_deadband=$HEADING_HOLD_ANGULAR_DEADBAND"
echo "[restart_nav] mecanum_forward_scale=$MECANUM_FORWARD_SCALE mecanum_lateral_scale=$MECANUM_LATERAL_SCALE mecanum_lateral_direction=$MECANUM_LATERAL_DIRECTION mecanum_angular_scale=$MECANUM_ANGULAR_SCALE"
echo "[restart_nav] auto_localizer_last_pose_file=$AUTO_LOCALIZER_LAST_POSE_FILE auto_localizer_enable_rotation=$AUTO_LOCALIZER_ENABLE_ROTATION auto_localizer_max_rotation_speed=$AUTO_LOCALIZER_MAX_ROTATION_SPEED auto_localizer_rotation_clearance=$AUTO_LOCALIZER_ROTATION_CLEARANCE"
echo "[restart_nav] auto_localizer_enable_escape=$AUTO_LOCALIZER_ENABLE_ESCAPE auto_localizer_escape_speed=$AUTO_LOCALIZER_ESCAPE_SPEED auto_localizer_escape_lateral_direction=$AUTO_LOCALIZER_ESCAPE_LATERAL_DIRECTION auto_localizer_escape_duration=$AUTO_LOCALIZER_ESCAPE_DURATION auto_localizer_escape_max_attempts=$AUTO_LOCALIZER_ESCAPE_MAX_ATTEMPTS"
echo "[restart_nav] enable_home_manager=$ENABLE_HOME_MANAGER enable_final_approach=$ENABLE_FINAL_APPROACH enable_patrol_manager=$ENABLE_PATROL_MANAGER patrol_route_file=$PATROL_ROUTE_FILE patrol_require_localization_ready=$PATROL_REQUIRE_LOCALIZATION_READY"
echo "[restart_nav] enable_waterplus_bridge=$ENABLE_WATERPLUS_BRIDGE waterplus_waypoints_file=$WATERPLUS_WAYPOINTS_FILE"
echo "[restart_nav] waterplus_default_waypoint_type=$WATERPLUS_DEFAULT_WAYPOINT_TYPE waterplus_default_final_approach=$WATERPLUS_DEFAULT_FINAL_APPROACH"
echo "[restart_nav] enable_waterplus_goal_pose_alias=$ENABLE_WATERPLUS_GOAL_POSE_ALIAS waterplus_goal_pose_topic=$WATERPLUS_GOAL_POSE_TOPIC"
echo "[restart_nav] nav2_goal_pose_topic=$NAV2_GOAL_POSE_TOPIC final_approach_goal_topic=$FINAL_APPROACH_GOAL_TOPIC"
echo "[restart_nav] enable_semantic_map=$ENABLE_SEMANTIC_MAP enable_named_navigation=$ENABLE_NAMED_NAVIGATION semantic_map_manifest=$SEMANTIC_MAP_MANIFEST"
echo "[restart_nav] enable_mission_control=$ENABLE_MISSION_CONTROL mission_state_file=$MISSION_STATE_FILE mission_zero_velocity_seconds=$MISSION_ZERO_VELOCITY_SECONDS mission_zero_velocity_hz=$MISSION_ZERO_VELOCITY_HZ"
echo "[restart_nav] enable_multifloor_manager=$ENABLE_MULTIFLOOR_MANAGER multifloor_building_config_file=$MULTIFLOOR_BUILDING_CONFIG_FILE multifloor_state_file=$MULTIFLOOR_STATE_FILE multifloor_current_floor_id=$MULTIFLOOR_CURRENT_FLOOR_ID"
echo "[restart_nav] enable_elevator_adapter=$ENABLE_ELEVATOR_ADAPTER enable_elevator_entry_controller=$ENABLE_ELEVATOR_ENTRY_CONTROLLER elevator_entry_params_file=$ELEVATOR_ENTRY_PARAMS_FILE"
echo "[restart_nav] lifecycle_bond_timeout=$LIFECYCLE_BOND_TIMEOUT lifecycle_startup_timeout=$LIFECYCLE_STARTUP_TIMEOUT lifecycle_stability_window=$LIFECYCLE_STABILITY_WINDOW nav_start_delay=$NAV_START_DELAY nav_node_batch_delay=$NAV_NODE_BATCH_DELAY mission_start_delay=$MISSION_START_DELAY navigation_startup_timeout=$NAVIGATION_STARTUP_TIMEOUT mission_startup_timeout=$MISSION_STARTUP_TIMEOUT"
echo "[restart_nav] lidar_ready_timeout=$LIDAR_READY_TIMEOUT lidar_startup_retries=$LIDAR_STARTUP_RETRIES lidar_retry_delay=$LIDAR_RETRY_DELAY lidar_preflight_timeout=$LIDAR_PREFLIGHT_TIMEOUT keep_stack_on_lidar_failure=$KEEP_STACK_ON_LIDAR_FAILURE"
echo "[restart_nav] navigation_rmw=$RMW_IMPLEMENTATION cyclonedds_uri=$CYCLONEDDS_URI"
echo "[restart_nav] log=$log"

setsid bash -lc "
  unset ROS_LOCALHOST_ONLY
  export ROS_AUTOMATIC_DISCOVERY_RANGE='${ROS_AUTOMATIC_DISCOVERY_RANGE}'
  export FASTDDS_BUILTIN_TRANSPORTS='${FASTDDS_BUILTIN_TRANSPORTS}'
  export RMW_IMPLEMENTATION='${RMW_IMPLEMENTATION}'
  export CYCLONEDDS_URI='${CYCLONEDDS_URI}'
  set +u
  source /opt/ros/humble/setup.bash
  source '$WS/install/setup.bash'
  set -u
  exec ros2 launch ddsm_car_control ddsm_bringup.launch.py mode:='$MODE' map:='$MAP' nav_params_file:='$NAV_PARAMS_FILE' slam_params_file:='$SLAM_PARAMS_FILE' ekf_params_file:='$EKF_PARAMS_FILE' max_linear_speed:='$MAX_LINEAR_SPEED' max_angular_speed:='$MAX_ANGULAR_SPEED' max_motor_rpm:='$MAX_MOTOR_RPM' cmd_freq:='$CMD_FREQ' timeout:='$TIMEOUT' low_cpu_nav:='$LOW_CPU_NAV' feedback_enabled:='$FEEDBACK_ENABLED' read_speed_feedback:='$READ_SPEED_FEEDBACK' feedback_freq:='$FEEDBACK_FREQ' free_ack_writes:='$FREE_ACK_WRITES' serial_timeout:='$SERIAL_TIMEOUT' imu_port:='$IMU_PORT' lidar_scan_frequency:='$LIDAR_SCAN_FREQUENCY' scan_publish_frequency:='$SCAN_PUBLISH_FREQUENCY' map_publish_frequency:='$MAP_PUBLISH_FREQUENCY' slam_map_update_interval:='$SLAM_MAP_UPDATE_INTERVAL' imu_heading_mode:='$IMU_HEADING_MODE' heading_pid_enabled:='$HEADING_PID_ENABLED' heading_pid_kp:='$HEADING_PID_KP' heading_pid_max_wz:='$HEADING_PID_MAX_WZ' heading_hold_min_vx:='$HEADING_HOLD_MIN_VX' heading_hold_angular_deadband:='$HEADING_HOLD_ANGULAR_DEADBAND' mecanum_forward_scale:='$MECANUM_FORWARD_SCALE' mecanum_lateral_scale:='$MECANUM_LATERAL_SCALE' mecanum_lateral_direction:='$MECANUM_LATERAL_DIRECTION' mecanum_angular_scale:='$MECANUM_ANGULAR_SCALE' laser_yaw:='$LASER_YAW' lifecycle_bond_timeout:='$LIFECYCLE_BOND_TIMEOUT' nav_start_delay:='$NAV_START_DELAY' nav_node_batch_delay:='$NAV_NODE_BATCH_DELAY' mission_start_delay:='$MISSION_START_DELAY' use_respawn:='$USE_RESPAWN' auto_localizer_last_pose_file:='$AUTO_LOCALIZER_LAST_POSE_FILE' auto_localizer_enable_rotation:='$AUTO_LOCALIZER_ENABLE_ROTATION' auto_localizer_max_rotation_speed:='$AUTO_LOCALIZER_MAX_ROTATION_SPEED' auto_localizer_rotation_clearance:='$AUTO_LOCALIZER_ROTATION_CLEARANCE' auto_localizer_enable_escape:='$AUTO_LOCALIZER_ENABLE_ESCAPE' auto_localizer_escape_speed:='$AUTO_LOCALIZER_ESCAPE_SPEED' auto_localizer_escape_lateral_direction:='$AUTO_LOCALIZER_ESCAPE_LATERAL_DIRECTION' auto_localizer_escape_duration:='$AUTO_LOCALIZER_ESCAPE_DURATION' auto_localizer_escape_max_attempts:='$AUTO_LOCALIZER_ESCAPE_MAX_ATTEMPTS' auto_localizer_warm_start_timeout:='$AUTO_LOCALIZER_WARM_START_TIMEOUT' auto_localizer_global_timeout:='$AUTO_LOCALIZER_GLOBAL_TIMEOUT' enable_home_manager:='$ENABLE_HOME_MANAGER' enable_final_approach:='$ENABLE_FINAL_APPROACH' enable_patrol_manager:='$ENABLE_PATROL_MANAGER' patrol_route_file:='$PATROL_ROUTE_FILE' patrol_require_localization_ready:='$PATROL_REQUIRE_LOCALIZATION_READY' enable_waterplus_bridge:='$ENABLE_WATERPLUS_BRIDGE' waterplus_waypoints_file:='$WATERPLUS_WAYPOINTS_FILE' waterplus_default_waypoint_type:='$WATERPLUS_DEFAULT_WAYPOINT_TYPE' waterplus_default_final_approach:='$WATERPLUS_DEFAULT_FINAL_APPROACH' enable_waterplus_goal_pose_alias:='$ENABLE_WATERPLUS_GOAL_POSE_ALIAS' waterplus_goal_pose_topic:='$WATERPLUS_GOAL_POSE_TOPIC' nav2_goal_pose_topic:='$NAV2_GOAL_POSE_TOPIC' final_approach_goal_topic:='$FINAL_APPROACH_GOAL_TOPIC' enable_lateral_escape_guard:='$ENABLE_LATERAL_ESCAPE_GUARD' nav_controller_cmd_vel_topic:='$NAV_CONTROLLER_CMD_VEL_TOPIC' lateral_escape_direction_sign:='$LATERAL_ESCAPE_DIRECTION_SIGN' semantic_map_manifest:='$SEMANTIC_MAP_MANIFEST' enable_semantic_map:='$ENABLE_SEMANTIC_MAP' enable_named_navigation:='$ENABLE_NAMED_NAVIGATION' enable_mission_control:='$ENABLE_MISSION_CONTROL' mission_state_file:='$MISSION_STATE_FILE' mission_zero_velocity_seconds:='$MISSION_ZERO_VELOCITY_SECONDS' mission_zero_velocity_hz:='$MISSION_ZERO_VELOCITY_HZ' enable_multifloor_manager:='$ENABLE_MULTIFLOOR_MANAGER' multifloor_building_config_file:='$MULTIFLOOR_BUILDING_CONFIG_FILE' multifloor_state_file:='$MULTIFLOOR_STATE_FILE' multifloor_current_floor_id:='$MULTIFLOOR_CURRENT_FLOOR_ID' enable_elevator_adapter:='$ENABLE_ELEVATOR_ADAPTER' enable_elevator_entry_controller:='$ENABLE_ELEVATOR_ENTRY_CONTROLLER' elevator_entry_params_file:='$ELEVATOR_ENTRY_PARAMS_FILE'
" 9>&- > "$log" 2>&1 < /dev/null &

pid="$!"
echo "$pid" > "$pidfile"
echo "[restart_nav] launch pid=$pid"
echo "[restart_nav] starting the voice command router"
XDG_RUNTIME_DIR=/run/user/1000 systemctl --user restart nav-llm-agent.service
for companion in voice-gateway.service luca-vision-bridge.service; do
  if ! XDG_RUNTIME_DIR=/run/user/1000 systemctl --user start "$companion"; then
    echo "[restart_nav] warning: $companion failed to start; check its user-service log"
  fi
done
echo "[restart_nav] waiting for startup..."
sleep 5
if [[ "$MODE" == "nav" || "$MODE" == "auto_nav" ]]; then
  if ! wait_for_log_pattern \
    'lifecycle_manager_localization.*Managed nodes are active' \
    'Nav2 localization lifecycle' \
    "$LIFECYCLE_STARTUP_TIMEOUT"; then
    echo "[restart_nav] latest log lines:"
    tail -n 80 "$log" || true
    exit 1
  fi
  if ! wait_for_localization_runtime_health "$LIFECYCLE_STARTUP_TIMEOUT"; then
    tail -n 80 "$log" || true
    exit 1
  fi
  echo "[restart_nav] observing lifecycle stability for ${LIFECYCLE_STABILITY_WINDOW}s"
  sleep "$LIFECYCLE_STABILITY_WINDOW"
  if grep -Eq 'lifecycle_manager_localization.*CRITICAL FAILURE' "$log"; then
    echo "[restart_nav] error: localization lifecycle failed during stability window"
    tail -n 80 "$log" || true
    exit 1
  fi
  ensure_foxglove_map_delivery
fi

if [[ "$MODE" == "auto_nav" ]]; then
  if ! wait_for_map_laser_with_retries; then
    tail -n 100 "$log" || true
    case "$KEEP_STACK_ON_LIDAR_FAILURE" in
      1|true|True|TRUE|yes|Yes|YES)
        echo "[restart_nav] warning: lidar is not ready; preserving the running map, base and camera processes"
        echo "[restart_nav] degraded startup retained; navigation will remain unavailable until lidar recovers"
        trap - EXIT
        exit 0
        ;;
      *)
        exit 1
        ;;
    esac
  fi
fi

if [[ "$MODE" == "auto_nav" ]]; then
  if ! wait_for_log_pattern \
    'lifecycle_manager_navigation_core.*Managed nodes are active' \
    'Nav2 core navigation lifecycle' \
    "$NAVIGATION_STARTUP_TIMEOUT"; then
    echo "[restart_nav] latest log lines:"
    tail -n 100 "$log" || true
    exit 1
  fi
  if ! wait_for_log_pattern \
    'lifecycle_manager_navigation_behavior.*Managed nodes are active' \
    'Nav2 behavior navigation lifecycle' \
    "$NAVIGATION_STARTUP_TIMEOUT"; then
    echo "[restart_nav] latest log lines:"
    tail -n 100 "$log" || true
    exit 1
  fi
  if [[ "$LOW_CPU_NAV" != "1" && "$LOW_CPU_NAV" != "true" && "$LOW_CPU_NAV" != "True" ]]; then
    if ! wait_for_log_pattern \
      'lifecycle_manager_navigation_safety.*Managed nodes are active' \
      'Nav2 safety navigation lifecycle' \
      "$NAVIGATION_STARTUP_TIMEOUT"; then
      echo "[restart_nav] latest log lines:"
      tail -n 100 "$log" || true
      exit 1
    fi
  fi
fi

if [[ "$MODE" == "nav" || "$MODE" == "auto_nav" ]] && [[ "$ENABLE_NAMED_NAVIGATION" != "false" && "$ENABLE_NAMED_NAVIGATION" != "False" && "$ENABLE_NAMED_NAVIGATION" != "0" ]]; then
  if ! wait_for_log_pattern \
    'hotel_named_navigation_server.*Named navigation ready' \
    'named navigation mission service' \
    "$MISSION_STARTUP_TIMEOUT"; then
    echo "[restart_nav] latest log lines:"
    tail -n 100 "$log" || true
    exit 1
  fi
fi

trap - EXIT

if ! XDG_RUNTIME_DIR=/run/user/1000 systemctl --user start person-follow.service; then
  echo "[restart_nav] warning: following service unavailable; navigation remains independent"
else
  echo "[restart_nav] following service available (idle; explicit activation required)"
fi

echo "[restart_nav] latest log lines:"
tail -n 40 "$log" || true

echo "[restart_nav] done. Foxglove: ws://${FOXGLOVE_HOST}:${FOXGLOVE_PORT}"
if [[ "$MODE" == "explore" ]]; then
  echo "[restart_nav] Explore mapping is active. Watch /map and /map_updates in Foxglove."
elif [[ "$MODE" == "auto_nav" ]]; then
  echo "[restart_nav] AMCL auto localization is active. Wait for /localization/status=localized, then send a navigation goal."
elif [[ "$MODE" == "nav" ]]; then
  echo "[restart_nav] Set the initial pose in Foxglove before sending a navigation goal."
fi
