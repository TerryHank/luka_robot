#!/usr/bin/env bash
set -euo pipefail

MODE="${LUKA_XIAOZHI_MODE:-mcp_only}"
WORKSPACE="${LUKA_WS:-/home/sunrise/luka_ws}"
runtime_dir="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/luka"
mkdir -p "$runtime_dir"
printf '%s\n' "$MODE" > "$runtime_dir/xiaozhi_mode"

resolve_root() {
  if [ -n "${XIAOZHI_RDK_ROOT:-}" ]; then
    printf '%s\n' "$XIAOZHI_RDK_ROOT"
  elif [ -f /home/sunrise/xiaozhi-in-rdk/mcp_pipe.py ]; then
    printf '%s\n' /home/sunrise/xiaozhi-in-rdk
  elif [ -f /opt/xiaozhi-in-rdk/mcp_pipe.py ]; then
    printf '%s\n' /opt/xiaozhi-in-rdk
  else
    return 1
  fi
}

case "$MODE" in
  off)
    echo "Xiaozhi integration disabled."
    exit 0
    ;;
  mcp_only)
    echo "Xiaozhi mode: mcp_only (Luka owns audio)"
    exec /bin/bash "$WORKSPACE/system/scripts/start_xiaozhi_mcp.sh"
    ;;
  exclusive_remote)
    if pgrep -af 'nx_voice_gateway.py|voice_gateway|sensevoice_ros2'         | grep -v 'start_xiaozhi_platform' >/dev/null 2>&1; then
      echo "Refusing exclusive_remote: a Luka/D-Robotics voice capture process is active." >&2
      echo "Stop the voice service first; two stacks must not own the microphone." >&2
      exit 21
    fi
    ROOT="$(resolve_root)" || {
      echo "xiaozhi-in-rdk not found; set XIAOZHI_RDK_ROOT" >&2
      exit 22
    }
    [ -f "$ROOT/xiaozhi-in-rdk.py" ] || {
      echo "Missing $ROOT/xiaozhi-in-rdk.py" >&2
      exit 23
    }
    [ -f "$ROOT/mcp_pipe.py" ] || {
      echo "Missing $ROOT/mcp_pipe.py" >&2
      exit 24
    }
    : "${MCP_ENDPOINT:?MCP_ENDPOINT is required in exclusive_remote mode}"
    export MCP_CONFIG="${MCP_CONFIG:-$WORKSPACE/system/xiaozhi/mcp_config.luka.json}"

    pids=()
    cleanup() {
      set +e
      for pid in "${pids[@]:-}"; do kill -TERM "$pid" 2>/dev/null || true; done
      for pid in "${pids[@]:-}"; do wait "$pid" 2>/dev/null || true; done
    }
    trap cleanup EXIT INT TERM

    echo "Xiaozhi mode: exclusive_remote"
    echo "  protocol: official xiaozhi-in-rdk MQTT + UDP/Opus"
    echo "  MCP:      official mcp_pipe -> Luka MCP server"
    (
      cd "$ROOT"
      exec python3 ./xiaozhi-in-rdk.py
    ) &
    pids+=("$!")
    (
      cd "$ROOT"
      exec python3 ./mcp_pipe.py
    ) &
    pids+=("$!")
    wait -n
    ;;
  *)
    echo "Unsupported LUKA_XIAOZHI_MODE=$MODE (off|mcp_only|exclusive_remote)" >&2
    exit 20
    ;;
esac
