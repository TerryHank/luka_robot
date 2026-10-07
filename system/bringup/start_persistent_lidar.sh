#!/usr/bin/env bash
set -uo pipefail

WS="${WS:-/home/sunrise/luka_ws}"
LOG_DIR="$WS/log/codex"
mkdir -p "$LOG_DIR"

exec 8>"$LOG_DIR/persistent_lidar.lock"
if ! flock -n 8; then
  echo "[persistent_lidar] another supervisor is already running"
  exit 0
fi
echo "$$" > "$LOG_DIR/persistent_lidar.pid"

set +u
source /opt/ros/humble/setup.bash
source "$WS/install/setup.bash"
set -u

unset ROS_LOCALHOST_ONLY
export ROS_AUTOMATIC_DISCOVERY_RANGE="${ROS_AUTOMATIC_DISCOVERY_RANGE:-SUBNET}"
export FASTDDS_BUILTIN_TRANSPORTS="${FASTDDS_BUILTIN_TRANSPORTS:-UDPv4}"
export RMW_IMPLEMENTATION="${NAV_RMW_IMPLEMENTATION:-rmw_cyclonedds_cpp}"
export CYCLONEDDS_URI="${NAV_CYCLONEDDS_URI:-file://$WS/common/config/cyclonedds_nav2.xml}"
LIDAR_WATCHDOG_STARTUP_GRACE="${LIDAR_WATCHDOG_STARTUP_GRACE:-15}"
LIDAR_WATCHDOG_INTERVAL="${LIDAR_WATCHDOG_INTERVAL:-5}"
UPPER_LIDAR_INTERFACE="${UPPER_LIDAR_INTERFACE:-eth1}"
UPPER_LIDAR_SOURCE_IP="${UPPER_LIDAR_SOURCE_IP:-192.168.11.10}"
UPPER_LIDAR_IP="${UPPER_LIDAR_IP:-192.168.11.2}"
UPPER_LIDAR_PORT="${UPPER_LIDAR_PORT:-8089}"
UPPER_LIDAR_PROXY_PORT="${UPPER_LIDAR_PROXY_PORT:-28089}"
UPPER_LIDAR_PROXY_SCRIPT="${UPPER_LIDAR_PROXY_SCRIPT:-$WS/src/ddsm_car_control/ddsm_car_control/low_lidar_udp_proxy.py}"

child_pid=""
proxy_pid=""
stop_child() {
  if [[ -n "$child_pid" ]] && kill -0 "$child_pid" 2>/dev/null; then
    kill -TERM -- "-$child_pid" 2>/dev/null || true
    for _ in {1..5}; do
      kill -0 "$child_pid" 2>/dev/null || break
      sleep 1
    done
    kill -KILL -- "-$child_pid" 2>/dev/null || true
    wait "$child_pid" 2>/dev/null || true
  fi
  if [[ -n "$proxy_pid" ]] && kill -0 "$proxy_pid" 2>/dev/null; then
    kill -TERM "$proxy_pid" 2>/dev/null || true
    wait "$proxy_pid" 2>/dev/null || true
  fi
  child_pid=""
  proxy_pid=""
  if [[ "$(cat "$LOG_DIR/persistent_lidar.pid" 2>/dev/null || true)" == "$$" ]]; then
    rm -f "$LOG_DIR/persistent_lidar.pid"
  fi
}
trap 'stop_child; exit 0' INT TERM

while true; do
  echo "[persistent_lidar] starting upper RPLIDAR via $UPPER_LIDAR_INTERFACE/$UPPER_LIDAR_SOURCE_IP $(date '+%F %T')"
  python3 "$UPPER_LIDAR_PROXY_SCRIPT" \
    --interface "$UPPER_LIDAR_INTERFACE" \
    --source-ip "$UPPER_LIDAR_SOURCE_IP" \
    --target-ip "$UPPER_LIDAR_IP" \
    --target-port "$UPPER_LIDAR_PORT" \
    --listen-port "$UPPER_LIDAR_PROXY_PORT" 8>&- &
  proxy_pid="$!"
  sleep 1
  if ! kill -0 "$proxy_pid" 2>/dev/null; then
    echo "[persistent_lidar] upper lidar UDP proxy failed to start; retrying in 3 seconds"
    proxy_pid=""
    sleep 3
    continue
  fi

  setsid ros2 run rplidar_ros rplidar_node --ros-args \
    -r __node:=rplidar_node \
    -p channel_type:=udp \
    -p udp_ip:=127.0.0.1 \
    -p udp_port:="$UPPER_LIDAR_PROXY_PORT" \
    -p frame_id:=laser \
    -p inverted:=false \
    -p angle_compensate:=true \
    -p scan_mode:=Sensitivity \
    -p scan_frequency:=12.0 \
    -p topic_name:=/scan_raw 8>&- &
  child_pid="$!"
  child_started_at="$SECONDS"
  while kill -0 "$child_pid" 2>/dev/null; do
    if timeout 5 ros2 topic echo /scan_raw --once \
      --field header.stamp.sec \
      --qos-reliability best_effort >/dev/null 2>&1; then
      sleep "$LIDAR_WATCHDOG_INTERVAL"
      continue
    fi
    if (( SECONDS - child_started_at >= LIDAR_WATCHDOG_STARTUP_GRACE )); then
      echo "[persistent_lidar] watchdog: process is alive but /scan_raw has no data; reconnecting"
      kill -TERM -- "-$child_pid" 2>/dev/null || true
      break
    fi
    sleep 1
  done
  status=0
  wait "$child_pid" || status="$?"
  child_pid=""
  if [[ -n "$proxy_pid" ]] && kill -0 "$proxy_pid" 2>/dev/null; then
    kill -TERM "$proxy_pid" 2>/dev/null || true
    wait "$proxy_pid" 2>/dev/null || true
  fi
  proxy_pid=""
  echo "[persistent_lidar] driver exited status=$status; retrying in 3 seconds"
  sleep 3
done
