#!/usr/bin/env bash
set -eo pipefail

# Read-only contract feature probe. It does not publish cmd_vel or call
# navigation/follow enable services.
source /home/sunrise/luka_ws/system/environment.bash

echo '== services =='
ros2 service list | grep -E 'navigation_enable|set_enabled|pause_now|resume_now' || true

echo '== sensor topics =='
for topic in /scan /scan_low_filtered /imu/data /amcl_pose; do
  echo "-- ${topic}"
  timeout 3 ros2 topic echo "${topic}" --once || true
done

echo '== vision bridge =='
timeout 3 ros2 topic echo /luka_person_following/adapter_status --once || true

echo '== navigation velocity graph =='
for topic in /nx/nav_raw /nx/nav_smoothed /nx/nav_guarded /nx/nav_safe; do
  echo "-- ${topic}"
  ros2 topic info "${topic}" -v || true
done

echo '== collision state =='
timeout 3 ros2 topic echo /collision_monitor_state --once || true
