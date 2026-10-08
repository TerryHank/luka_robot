#!/usr/bin/env bash
set -eo pipefail
source /home/sunrise/luka_ws/src/system/environment.bash
mkdir -p /home/sunrise/luka_ws/log/owners
exec 9>/home/sunrise/luka_ws/log/owners/visual-runtime.lock
flock -n 9 || { echo 'Visual runtime already owned by another canonical entrypoint' >&2; exit 1; }
export NX_CAMERA_SOURCE="${NX_CAMERA_SOURCE:-orbbec_ros}"
if [[ "$NX_CAMERA_SOURCE" != orbbec_ros ]]; then echo "Current visual runtime reuses ROS RGB-D; native camera backends are retired" >&2; exit 1; fi
exec /usr/bin/python3 /home/sunrise/luka_ws/src/perception/luka_visual_runtime/live_app.py
