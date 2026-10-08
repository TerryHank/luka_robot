#!/usr/bin/env bash
set -eo pipefail
source /home/sunrise/luka_ws/src/system/environment.bash
ros2 node list
ros2 action info /navigate_to_pose
for topic in /scan /odom /map /global_costmap/costmap /nx/nav_safe; do
  ros2 topic info "$topic" -v || true
done
