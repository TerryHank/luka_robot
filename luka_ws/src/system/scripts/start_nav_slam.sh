#!/usr/bin/env bash
set -euo pipefail
cd /home/nvidia/ddsm_car_ws
mkdir -p logs
/home/nvidia/ddsm_car_ws/scripts/stop_nav.sh >/dev/null 2>&1 || true
nohup setsid bash -lc 'source /home/nvidia/ddsm_car_ws/scripts/ros_env.sh && exec ros2 launch ddsm_car_control ddsm_nav_slam.launch.py use_respawn:=False' \
  > /home/nvidia/ddsm_car_ws/logs/ddsm_nav_slam.log 2>&1 < /dev/null &
echo $! > /home/nvidia/ddsm_car_ws/logs/ddsm_nav_slam.pid
echo "started ddsm_nav_slam pid=$(cat /home/nvidia/ddsm_car_ws/logs/ddsm_nav_slam.pid)"
