#!/bin/bash
set -eo pipefail
source /opt/ros/humble/setup.bash
export ROS_DOMAIN_ID=87 ROS_LOCALHOST_ONLY=1 RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI=file:///home/sunrise/luka_ws/src/common/config/cyclonedds_offline.xml
exec python3 /home/sunrise/luka_ws/src/system/runtime/tools/nx_sonar_ros.py
