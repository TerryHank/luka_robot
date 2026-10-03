#!/usr/bin/env bash
set -eo pipefail
source /home/nvidia/ddsm_car_ws/scripts/ros_env.sh
echo "RMW=$RMW_IMPLEMENTATION"
echo "CYCLONEDDS_URI=$CYCLONEDDS_URI"
echo "--- processes ---"
pgrep -af 'ddsm_nav_slam|ddsm_nav2|udp_cmd_vel_bridge|encoder_logger|rplidar_node|async_slam_toolbox_node|controller_server|planner_server|bt_navigator|velocity_smoother|lifecycle_manager' || true
echo "--- lifecycle ---"
for node in /slam_toolbox /controller_server /planner_server /bt_navigator /velocity_smoother /local_costmap/local_costmap /global_costmap/global_costmap; do
  printf '%s ' "$node"
  timeout 4 ros2 lifecycle get "$node" || true
done
echo "--- topics ---"
ros2 topic list -t | grep -E '^/(scan|odom|map|local_costmap/costmap|global_costmap/costmap|cmd_vel|cmd_vel_smoothed|cmd_vel_nav|navigate_to_pose)' | sort || true
