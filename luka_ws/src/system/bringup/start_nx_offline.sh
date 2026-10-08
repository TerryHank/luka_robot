#!/bin/bash
set -eo pipefail
source /opt/ros/humble/setup.bash
source /home/sunrise/luka_ws/install/setup.bash
export ROS_DOMAIN_ID=87
export ROS_LOCALHOST_ONLY=1
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI=file:///home/sunrise/luka_ws/common/config/cyclonedds_offline.xml
exec ros2 launch ddsm_car_control ddsm_bringup.launch.py \
 mode:=nav map:=/home/sunrise/luka_ws/map/maps/ddsm_map_floor_4.yaml \
 nav_params_file:=/home/sunrise/luka_ws/install/ddsm_car_control/share/ddsm_car_control/config/nav2_mecanum_mppi_params.yaml \
 nav_start_delay:=1.0 nav_node_batch_delay:=0.5 mission_start_delay:=3.0 \
 enable_base_driver:=false enable_imu:=false enable_lidar:=false \
 start_lidar_driver:=false enable_dual_lidar:=false enable_scan_deskew:=false \
 enable_ekf:=false enable_depth_camera:=false enable_colored_point_cloud:=false \
 enable_depth_obstacle_fusion:=false enable_semantic_mapping:=false \
 enable_auto_localizer:=false auto_localizer_enable_rotation:=false auto_localizer_enable_escape:=false \
 enable_patrol_manager:=false enable_waterplus_bridge:=false enable_named_navigation:=false \
 enable_mission_control:=false enable_home_manager:=false enable_final_approach:=false \
 enable_lateral_escape_guard:=false enable_multifloor_manager:=false \
 enable_elevator_adapter:=false enable_elevator_entry_controller:=false enable_llm_agent:=false \
 enable_teleop:=false enable_slam:=false enable_explore:=false \
 enable_nav:=auto low_cpu_nav:=true enable_semantic_map:=true
