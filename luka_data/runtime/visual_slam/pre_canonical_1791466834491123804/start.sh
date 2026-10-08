#!/usr/bin/env bash
set -eo pipefail
source /home/sunrise/luka_ws/src/system/environment.bash
available_kib=$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)
if [ "$available_kib" -lt 1536000 ]; then
  echo 'RTAB-Map experiment needs at least 1500 MiB available RAM.' >&2
  exit 1
fi
mkdir -p /home/sunrise/luka_ws/log/owners
exec 8>/home/sunrise/luka_ws/log/owners/rtabmap-rgbd-experiment.lock
flock -n 8 || { echo 'RGB-D experiment already running.' >&2; exit 1; }
run_dir=/home/sunrise/luka_data/maps/rtabmap_rgbd/$(date +%Y%m%d_%H%M%S_%N)
mkdir -p "$run_dir"
export ROS_LOG_DIR=/home/sunrise/luka_ws/log/rtabmap_rgbd
echo "RTAB-Map database: $run_dir/map.db"
exec ros2 launch /home/sunrise/luka_ws/src/localization/rtabmap_rgbd_experiment/rgbd_isolated.launch.py database_path:="$run_dir/map.db" "$@"
