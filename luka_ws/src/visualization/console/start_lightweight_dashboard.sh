#!/usr/bin/env bash
set -eo pipefail

WS="${WS:-$HOME/ddsm_car_ws}"
PORT="${LIGHT_DASHBOARD_PORT:-8503}"
PID_FILE="/tmp/ddsm_lightweight_dashboard.pid"
LOG_FILE="/tmp/ddsm_lightweight_dashboard.log"
PROGRAM="$WS/system/runtime/tools/lightweight_robot_dashboard.py"

dashboard_url() {
  local ip
  ip="$(ip -4 -o addr show scope global | awk '$4 ~ /^192\.168\.3\./ {sub(/\/.*/, "", $4); print $4; exit}')"
  ip="${ip:-$(hostname -I | awk '{print $1}')}"
  printf 'http://%s:%s' "$ip" "$PORT"
}

source /opt/ros/humble/setup.bash
source "$WS/install/setup.bash"
export RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_cyclonedds_cpp}"
export CYCLONEDDS_URI="${CYCLONEDDS_URI:-file://$WS/common/config/cyclonedds_nav2.xml}"
set -u

dashboard_running() {
  [[ -s "$PID_FILE" ]] || return 1
  local pid
  pid="$(cat "$PID_FILE")"
  kill -0 "$pid" 2>/dev/null || return 1
  tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | grep -Fq "$PROGRAM"
}

case "${1:-start}" in
  start)
      if dashboard_running; then
        echo "Dashboard already running: $(dashboard_url)"
        exit 0
      fi
      rm -f "$PID_FILE"
      nohup env LIGHT_DASHBOARD_PORT="$PORT" DDSM_WS="$WS" python3 "$PROGRAM" >"$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    sleep 1
    if ! kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      cat "$LOG_FILE"
      exit 1
    fi
    echo "Dashboard started: $(dashboard_url)"
    ;;
    stop)
      if dashboard_running; then
        kill "$(cat "$PID_FILE")" 2>/dev/null || true
        for _ in {1..20}; do
          kill -0 "$(cat "$PID_FILE")" 2>/dev/null || break
          sleep 0.1
        done
      fi
      rm -f "$PID_FILE"
      echo "Dashboard stopped"
    ;;
  restart)
    "$0" stop
    "$0" start
    ;;
    status)
      if dashboard_running; then
        echo "running pid=$(cat "$PID_FILE") port=$PORT"
    else
      echo "stopped"
      exit 1
    fi
    ;;
  *)
    echo "Usage: $0 {start|stop|restart|status}" >&2
    exit 2
    ;;
esac
