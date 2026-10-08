#!/usr/bin/env bash
set -u
patterns=(
  "ros2 launch ddsm_car_control ddsm_nav_slam.launch.py"
  "ros2 launch ddsm_car_control ddsm_nav2.launch.py"
  "ros2 launch ddsm_car_control ddsm_slam.launch.py"
  "ros2 launch ddsm_car_control ddsm_robot_bringup.launch.py"
  "udp_cmd_vel_bridge"
  "encoder_logger"
  "rplidar_node"
  "static_transform_publisher --x 0.065"
  "async_slam_toolbox_node"
  "controller_server"
  "smoother_server"
  "planner_server"
  "route_server"
  "behavior_server"
  "bt_navigator"
  "waypoint_follower"
  "velocity_smoother"
  "collision_monitor"
  "opennav_docking"
  "nav2_lifecycle_manager/lifecycle_manager"
)
for pattern in "${patterns[@]}"; do
  pkill -INT -f "$pattern" 2>/dev/null || true
done
sleep 3
for pattern in "${patterns[@]}"; do
  pkill -TERM -f "$pattern" 2>/dev/null || true
done
sleep 2
for pattern in "${patterns[@]}"; do
  pkill -KILL -f "$pattern" 2>/dev/null || true
done
rm -f /home/nvidia/ddsm_car_ws/logs/ddsm_nav_slam.pid /home/nvidia/ddsm_car_ws/logs/ddsm_nav2.pid
