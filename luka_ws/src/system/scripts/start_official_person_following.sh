#!/usr/bin/env bash
set -eo pipefail
source /home/sunrise/luka_ws/src/system/environment.bash
source /home/sunrise/luka_ws/src/system/scripts/person_follow_environment.bash
exec ros2 launch s100_person_following_integration s100_person_following_integration.launch.py start_segmentation:=true "$@"
