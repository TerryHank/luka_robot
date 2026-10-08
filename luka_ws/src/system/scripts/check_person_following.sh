#!/usr/bin/env bash
set -eo pipefail
_follow_ws=/home/sunrise/luka_ws
source "$_follow_ws/src/system/scripts/person_follow_environment.bash"
cd "$_follow_ws"
python3 src/system/scripts/check_workspace_root.py
colcon list --base-paths src
# Each test uses an isolated localhost DDS domain; production domain 87 is excluded.
ROS_LOCALHOST_ONLY=1 colcon test --base-paths src \
  --packages-select s100_person_following_integration --executor sequential
colcon test-result --test-result-base build/s100_person_following_integration --verbose
if [[ "${1:-}" == --live-audit ]]; then
  ros2 run s100_person_following_integration preflight.py
fi
