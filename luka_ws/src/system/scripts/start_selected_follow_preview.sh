#!/usr/bin/env bash
set -eo pipefail
source /home/sunrise/luka_ws/system/environment.bash
exec ros2 launch luka_person_following selected_follow.launch.py dry_run:=true
