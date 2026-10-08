#!/usr/bin/env bash
set -euo pipefail
cd /home/nvidia/ddsm_car_ws
mkdir -p logs
/home/nvidia/ddsm_car_ws/scripts/stop_nav.sh >/dev/null 2>&1 || true
MAP_FILE=${1:-/home/nvidia/ddsm_car_ws/maps/ddsm_map.yaml}
nohup setsid bash -lc "source /home/nvidia/ddsm_car_ws/scripts/ros_env.sh && exec ros2 launch ddsm_car_control ddsm_nav2.launch.py map:=${MAP_FILE} use_respawn:=False" \
  > /home/nvidia/ddsm_car_ws/logs/ddsm_nav2.log 2>&1 < /dev/null &
echo $! > /home/nvidia/ddsm_car_ws/logs/ddsm_nav2.pid
echo "started ddsm_nav2 pid=$(cat /home/nvidia/ddsm_car_ws/logs/ddsm_nav2.pid) map=${MAP_FILE}"
