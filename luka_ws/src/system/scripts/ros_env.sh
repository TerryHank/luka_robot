#!/usr/bin/env bash
set -e
source /opt/ros/humble/setup.bash
[ -f /home/nvidia/driver_ws/install/setup.bash ] && source /home/nvidia/driver_ws/install/setup.bash
[ -f /home/nvidia/ddsm_car_ws/install/setup.bash ] && source /home/nvidia/ddsm_car_ws/install/setup.bash
export ROS_DOMAIN_ID=0
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
export ROS_LOCALHOST_ONLY=0
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI=file:///home/nvidia/ddsm_car_ws/config/cyclonedds_nav2.xml
