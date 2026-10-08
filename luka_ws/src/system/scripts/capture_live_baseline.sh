#!/usr/bin/env bash
set -euo pipefail
ROOT="${1:-/home/sunrise/luka_ws}"
OUT="${2:-$ROOT/docs/suite/live}"
DEST="$OUT/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$DEST"
if [ -f /opt/tros/humble/setup.bash ]; then source /opt/tros/humble/setup.bash
elif [ -f /opt/ros/humble/setup.bash ]; then source /opt/ros/humble/setup.bash
fi
if [ -f "$ROOT/install/local_setup.bash" ]; then source "$ROOT/install/local_setup.bash"; fi
{
 echo "captured_at=$(date --iso-8601=seconds)"
 echo "hostname=$(hostname)"
 echo "kernel=$(uname -a)"
 echo "ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-}"
 echo "ROS_LOCALHOST_ONLY=${ROS_LOCALHOST_ONLY:-}"
 echo "RMW_IMPLEMENTATION=${RMW_IMPLEMENTATION:-}"
} > "$DEST/environment.txt"
ros2 node list > "$DEST/nodes.txt" || true
ros2 topic list -t > "$DEST/topics.txt" || true
ros2 service list -t > "$DEST/services.txt" || true
ros2 action list -t > "$DEST/actions.txt" || true
ros2 pkg list > "$DEST/packages.txt" || true
timeout 3s ros2 run tf2_ros tf2_echo map base_footprint > "$DEST/tf_map_base.txt" 2>&1 || true
timeout 3s ros2 run tf2_ros tf2_echo base_footprint camera_link > "$DEST/tf_base_camera.txt" 2>&1 || true
printf 'Read-only capture complete: %s\n' "$DEST"
