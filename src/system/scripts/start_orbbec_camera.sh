#!/usr/bin/env bash
set -eo pipefail
source /home/sunrise/luka_ws/src/system/environment.bash
mkdir -p /home/sunrise/luka_ws/log/owners
exec 9>/home/sunrise/luka_ws/log/owners/astra-camera.lock
flock -n 9 || { echo 'Astra camera already owned by another canonical entrypoint' >&2; exit 1; }
# SDK log/crash files are relative to cwd; keep them in the workspace log tree.
mkdir -p /home/sunrise/luka_ws/log/orbbec_camera
cd /home/sunrise/luka_ws/log/orbbec_camera
exec ros2 launch orbbec_camera astra_pro_plus.launch.py camera_name:=camera enable_ir:=false enable_point_cloud:=false enable_colored_point_cloud:=false depth_registration:=true align_mode:=SW color_width:=640 color_height:=480 depth_width:=640 depth_height:=480
