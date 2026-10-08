#!/usr/bin/env bash
set -Eeuo pipefail

WS="${WS:-/home/sunrise/luka_ws}"
MODE="${MODE:-explore}"
RESTART_FOXGLOVE="${RESTART_FOXGLOVE:-0}"
MAX_LINEAR_SPEED="${MAX_LINEAR_SPEED:-0.3}"
LIDAR_SCAN_FREQUENCY="${LIDAR_SCAN_FREQUENCY:-8.0}"
TIMEOUT="${TIMEOUT:-0.65}"
SCAN_PUBLISH_FREQUENCY="${SCAN_PUBLISH_FREQUENCY:-3.0}"
MAP_PUBLISH_FREQUENCY="${MAP_PUBLISH_FREQUENCY:-1.5}"
SLAM_MAP_UPDATE_INTERVAL="${SLAM_MAP_UPDATE_INTERVAL:-0.7}"
EKF_PARAMS_FILE="${EKF_PARAMS_FILE:-$WS/install/ddsm_car_control/share/ddsm_car_control/config/ekf_explore.yaml}"
USE_RESPAWN="${USE_RESPAWN:-False}"
NAV_PARAMS_FILE="${NAV_PARAMS_FILE:-$WS/install/ddsm_car_control/share/ddsm_car_control/config/nav2_explore_params.yaml}"
SLAM_PARAMS_FILE="${SLAM_PARAMS_FILE:-$NAV_PARAMS_FILE}"

echo "[restart_explore] starting auto explore mapping"
echo "[restart_explore] mode=$MODE foxglove_restart=$RESTART_FOXGLOVE max_linear_speed=$MAX_LINEAR_SPEED timeout=$TIMEOUT lidar_scan_frequency=$LIDAR_SCAN_FREQUENCY scan_publish_frequency=$SCAN_PUBLISH_FREQUENCY map_publish_frequency=$MAP_PUBLISH_FREQUENCY slam_map_update_interval=$SLAM_MAP_UPDATE_INTERVAL"
echo "[restart_explore] Foxglove live map topics: /map and /map_updates"

exec env \
  WS="$WS" \
  MODE="$MODE" \
  RESTART_FOXGLOVE="$RESTART_FOXGLOVE" \
  MAX_LINEAR_SPEED="$MAX_LINEAR_SPEED" \
  TIMEOUT="$TIMEOUT" \
  LIDAR_SCAN_FREQUENCY="$LIDAR_SCAN_FREQUENCY" \
  SCAN_PUBLISH_FREQUENCY="$SCAN_PUBLISH_FREQUENCY" \
  MAP_PUBLISH_FREQUENCY="$MAP_PUBLISH_FREQUENCY" \
  SLAM_MAP_UPDATE_INTERVAL="$SLAM_MAP_UPDATE_INTERVAL" \
  EKF_PARAMS_FILE="$EKF_PARAMS_FILE" \
  SLAM_PARAMS_FILE="$SLAM_PARAMS_FILE" \
  USE_RESPAWN="$USE_RESPAWN" \
  NAV_PARAMS_FILE="$NAV_PARAMS_FILE" \
  "$WS/restart_nav_reset.sh"
