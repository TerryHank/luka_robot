#!/usr/bin/env bash
set -eo pipefail
source /home/sunrise/luka_ws/system/environment.bash
exec ros2 launch orbbec_camera astra_pro_plus.launch.py camera_name:=camera enable_ir:=false enable_point_cloud:=false enable_colored_point_cloud:=false depth_registration:=true align_mode:=SW color_width:=640 color_height:=480 depth_width:=640 depth_height:=480
