#!/usr/bin/env bash
set -euo pipefail

# P10 read-only preflight. This script MUST NOT publish Twist, send a Nav2 goal,
# enable navigation/following, or touch motor serial devices.

ROOT="${1:-/home/sunrise/luka_ws}"
OUT="${2:-$ROOT/docs/suite/p10/live}"
DEST="$OUT/$(date +%Y%m%d_%H%M%S)_preflight"
mkdir -p "$DEST"

if [ -f /opt/tros/humble/setup.bash ]; then source /opt/tros/humble/setup.bash; fi
if [ -f /opt/ros/humble/setup.bash ]; then source /opt/ros/humble/setup.bash; fi
if [ -f "$ROOT/install/local_setup.bash" ]; then source "$ROOT/install/local_setup.bash"; fi

fail=0
note_fail() { echo "FAIL: $*" | tee -a "$DEST/result.txt"; fail=1; }
note_ok() { echo "OK: $*" | tee -a "$DEST/result.txt"; }

{
  echo "captured_at=$(date --iso-8601=seconds)"
  echo "hostname=$(hostname)"
  echo "kernel=$(uname -a)"
  echo "ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-}"
  echo "ROS_LOCALHOST_ONLY=${ROS_LOCALHOST_ONLY:-}"
  echo "RMW_IMPLEMENTATION=${RMW_IMPLEMENTATION:-}"
  if command -v git >/dev/null 2>&1 && [ -d "$ROOT/.git" ]; then
    echo "git_branch=$(git -C "$ROOT" branch --show-current)"
    echo "git_head=$(git -C "$ROOT" rev-parse HEAD)"
    echo "git_dirty=$(test -n "$(git -C "$ROOT" status --porcelain)" && echo 1 || echo 0)"
  fi
} > "$DEST/environment.txt"

ros2 node list > "$DEST/nodes.txt" || true
ros2 topic list -t > "$DEST/topics.txt" || true
ros2 service list -t > "$DEST/services.txt" || true
ros2 action list -t > "$DEST/actions.txt" || true

for pair in   "map base_footprint tf_map_base"   "map camera_link tf_map_camera"   "base_footprint camera_link tf_base_camera"; do
  set -- $pair
  timeout 3s ros2 run tf2_ros tf2_echo "$1" "$2"     > "$DEST/$3.txt" 2>&1 || true
done

for topic in   /luka/perception/person_targets   /luka/follow/selected_target   /luka_person_following/adapter_status   /collision_monitor_state   /amcl_pose   /nx/nav_raw   /nx/nav_smoothed   /nx/nav_guarded   /nx/nav_safe; do
  safe="$(echo "$topic" | tr '/' '_' | sed 's/^_//')"
  ros2 topic info "$topic" -v > "$DEST/topic_$safe.txt" 2>&1 || true
done

for service in   /nx/navigation_enable   /luka_person_following/set_enabled   /luka_person_following/official/enable_follow; do
  safe="$(echo "$service" | tr '/' '_' | sed 's/^_//')"
  ros2 service type "$service" > "$DEST/service_$safe.txt" 2>&1 || true
done

ros2 action info /navigate_to_pose > "$DEST/action_navigate_to_pose.txt" 2>&1 || true

timeout 3s ros2 topic echo /collision_monitor_state --once   > "$DEST/collision_monitor_state.txt" 2>&1 || true
timeout 3s ros2 topic echo /amcl_pose --once   > "$DEST/amcl_pose.txt" 2>&1 || true
timeout 3s ros2 topic echo /luka_person_following/adapter_status --once   > "$DEST/follow_adapter_status.txt" 2>&1 || true

grep -Ei 'laser_scan|sensor_msgs/msg/LaserScan' "$DEST/topics.txt"   > "$DEST/lidar_topics.txt" || true

grep -nE 'cmd_vel_(in|out)_topic: /nx/nav_(guarded|safe)|cmd_vel_out_topic: /nx/nav_guarded'   "$ROOT/common/config/nx_nav2.yaml"   "$ROOT/common/config/nx_heading_guard.yaml"   > "$DEST/safety_chain_config.txt" 2>&1 || true
grep -nE 'nav_cmd_vel_topic: /nx/nav_safe'   "$ROOT/common/config/nx_manual_base.yaml"   > "$DEST/base_input_config.txt" 2>&1 || true

if ! grep -q '/luka/perception/person_targets' "$DEST/topics.txt"; then
  note_fail "ROS-native person target topic missing"
else note_ok "ROS-native person target topic present"; fi

if ! grep -q '/collision_monitor_state' "$DEST/topics.txt"; then
  note_fail "collision monitor state topic missing"
else note_ok "collision monitor topic present"; fi

if ! grep -q '/nx/navigation_enable' "$DEST/services.txt"; then
  note_fail "navigation permission service missing"
else note_ok "navigation permission service present"; fi

if ! grep -q '/luka_person_following/set_enabled' "$DEST/services.txt"; then
  note_fail "follow enable service missing"
else note_ok "follow enable service present"; fi

if [ ! -s "$DEST/lidar_topics.txt" ]; then
  note_fail "no LaserScan topic discovered"
else note_ok "LaserScan topic discovered"; fi

if ! grep -q '/nx/nav_safe' "$DEST/base_input_config.txt"; then
  note_fail "DDSM/base nav input is not proven to be /nx/nav_safe"
else note_ok "base nav input config points to /nx/nav_safe"; fi

cat >> "$DEST/result.txt" <<'EOF'

MANUAL GATES — MUST be confirmed by the onsite operator before any P10 motion:
[ ] Physical emergency-stop/kill method is reachable and tested.
[ ] Robot is in a controlled test area with a spotter.
[ ] Stage 1: wheels are physically suspended from the ground.
[ ] Stage 2+: temporary low-speed limits are applied and independently verified.
[ ] Battery, motor controller and mechanical fasteners are safe for the test.
EOF

echo "P10 read-only preflight: $DEST"
echo "No motion command was sent."
exit "$fail"
