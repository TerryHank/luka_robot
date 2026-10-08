#!/usr/bin/env bash
# Expose local Qwen3 (127.0.0.1:11434) to RK3588 via SSH reverse tunnel.
# On the board, Agent then uses http://127.0.0.1:11434 as usual.
set -eo pipefail

REMOTE="${RK3588_SSH_HOST:-rk3588}"
LOCAL_PORT="${OLLAMA_PORT:-11434}"
REMOTE_PORT="${REMOTE_OLLAMA_PORT:-11434}"

if ! ss -ltn | grep -q ":${LOCAL_PORT} "; then
  echo "本机 ${LOCAL_PORT} 未监听。请先启动:" >&2
  echo "  bash ~/ros2_ws/src/nav_llm_agent/scripts/start_qwen3_server.sh" >&2
  exit 1
fi

echo "反向隧道: ${REMOTE}:${REMOTE_PORT} -> 本机 127.0.0.1:${LOCAL_PORT}"
echo "板上验证: ssh ${REMOTE} 'curl -s -o /dev/null -w %{http_code} http://127.0.0.1:${REMOTE_PORT}/'"
exec ssh -N -o ExitOnForwardFailure=yes -R "${REMOTE_PORT}:127.0.0.1:${LOCAL_PORT}" "${REMOTE}"
