#!/usr/bin/env bash
set -eo pipefail
source /home/sunrise/luka_ws/src/system/environment.bash
available_kib=$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)
[ "$available_kib" -ge 1536000 ] || { echo 'Visual SLAM needs at least 1500 MiB available RAM.' >&2; exit 1; }
mkdir -p /home/sunrise/luka_ws/log/owners
exec 8>/home/sunrise/luka_ws/log/owners/rtabmap-rgbd-experiment.lock
flock -n 8 || { echo 'Visual SLAM already running.' >&2; exit 1; }
export ROS_LOG_DIR=/home/sunrise/luka_ws/log/visual_slam
exec ros2 launch luka_visual_slam visual_slam.launch.py "$@"
