#!/usr/bin/env bash
set -euo pipefail

# Read-only P10 metrics snapshot. It never enables motion.
ROOT="${1:-/home/sunrise/luka_ws}"
OUT="${2:-$ROOT/docs/suite/p10/live}"
DEST="$OUT/$(date +%Y%m%d_%H%M%S)_metrics"
mkdir -p "$DEST"

if [ -f /opt/tros/humble/setup.bash ]; then source /opt/tros/humble/setup.bash; fi
if [ -f /opt/ros/humble/setup.bash ]; then source /opt/ros/humble/setup.bash; fi
if [ -f "$ROOT/install/local_setup.bash" ]; then source "$ROOT/install/local_setup.bash"; fi

date --iso-8601=seconds > "$DEST/time.txt"
uptime > "$DEST/uptime.txt" || true
free -h > "$DEST/memory.txt" || true
ps -eo pid,ppid,comm,%cpu,%mem,rss --sort=-%cpu | head -80   > "$DEST/processes.txt" || true

if [ -d /sys/class/thermal ]; then
  for zone in /sys/class/thermal/thermal_zone*; do
    [ -e "$zone" ] || continue
    {
      printf '%s ' "$(basename "$zone")"
      cat "$zone/type" 2>/dev/null || printf 'unknown'
      printf ' '
      cat "$zone/temp" 2>/dev/null || printf 'unknown'
      printf '\n'
    } >> "$DEST/thermal.txt"
  done
fi

for command in hobot-smi hrut_somstatus; do
  if command -v "$command" >/dev/null 2>&1; then
    timeout 5s "$command" > "$DEST/$command.txt" 2>&1 || true
  fi
done

for topic in   /camera/color/image_raw   /luka/perception/person_targets   /luka/follow/selected_target   /nx/nav_safe; do
  safe="$(echo "$topic" | tr '/' '_' | sed 's/^_//')"
  timeout 8s ros2 topic hz "$topic" > "$DEST/hz_$safe.txt" 2>&1 || true
done

timeout 3s ros2 topic echo /luka/perception/person_diagnostics --once   > "$DEST/person_diagnostics.txt" 2>&1 || true
timeout 3s ros2 topic echo /luka_person_following/adapter_status --once   > "$DEST/follow_status.txt" 2>&1 || true
timeout 3s ros2 topic echo /collision_monitor_state --once   > "$DEST/collision_state.txt" 2>&1 || true

echo "Read-only P10 metrics captured: $DEST"
