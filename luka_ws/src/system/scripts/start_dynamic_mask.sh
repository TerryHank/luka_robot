#!/usr/bin/env bash
set -eo pipefail
source /home/sunrise/luka_ws/src/system/environment.bash
exec ros2 run luka_image_inference dynamic_mask "$@"
