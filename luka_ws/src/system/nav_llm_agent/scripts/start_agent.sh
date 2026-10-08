#!/usr/bin/env bash
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/_source_ws.sh"

# Real robot (RK3588 / LubanCat): wall clock. WSL sim: use_sim_time true.
if [[ -z "${USE_SIM_TIME:-}" ]]; then
  if [[ "${ROS_WS:-}" == *ddsm_car_ws* ]] || [[ "$(uname -m)" == "aarch64" ]]; then
    USE_SIM_TIME=false
  else
    USE_SIM_TIME=true
  fi
fi

# Board defaults: on-device Qwen2.5 via llama-server (OpenAI-compatible :8080).
# WSL sim keeps Qwen3 Ollama-compat on :11434 unless overridden.
BOARD_QWEN25_MODEL="${BOARD_QWEN25_MODEL:-/home/nvidia/pan/Qwen2.5-1.5B/models/Qwen2.5-1.5B-Instruct-Q8_0.gguf}"
EXTRA_ARGS=()
if [[ "${ROS_WS:-}" == *ddsm_car_ws* ]] || [[ "$(uname -m)" == "aarch64" ]]; then
  OLLAMA_URL="${OLLAMA_URL:-http://127.0.0.1:8080}"
  MODEL="${MODEL:-${BOARD_QWEN25_MODEL}}"
  LLM_API="${LLM_API:-openai}"
  LLM_LABEL="Qwen2.5-1.5B (板上 llama-server)"
else
  OLLAMA_URL="${OLLAMA_URL:-http://127.0.0.1:11434}"
  MODEL="${MODEL:-qwen3:1.7b}"
  LLM_API="${LLM_API:-ollama}"
  LLM_LABEL="Qwen3-1.7B (本机)"
fi
EXTRA_ARGS+=(
  "ollama_url:=${OLLAMA_URL}"
  "model:=${MODEL}"
  "llm_api:=${LLM_API}"
)

echo "=============================================="
echo "  Nav LLM Agent — ${LLM_LABEL}"
echo "  workspace: ${ROS_WS:-unknown}"
echo "  use_sim_time: ${USE_SIM_TIME}"
echo "  llm: ${LLM_API} ${OLLAMA_URL}  model=${MODEL}"
echo "  订阅: /llm_command"
echo "  状态: /llm_status"
if [[ "$(uname -m)" == "aarch64" ]] || [[ "${ROS_WS:-}" == *ddsm_car_ws* ]]; then
  echo "  先启动:"
  echo "    1) 导航栈: ~/ddsm_car_ws/restart_nav_reset.sh"
  echo "    2) 板上 Qwen2.5: systemctl status llama-chat.service  (127.0.0.1:8080)"
else
  echo "  先启动:"
  echo "    1) 导航栈: start_navigation.sh"
  echo "    2) Qwen3: start_qwen3_server.sh"
fi
echo "  保存航点: bash ${SCRIPT_DIR}/save_waypoint.sh"
echo "  发指令:   bash ${SCRIPT_DIR}/send_command.sh '去厨房'"
echo "=============================================="

exec ros2 launch nav_llm_agent agent.launch.py \
  use_sim_time:="${USE_SIM_TIME}" \
  "${EXTRA_ARGS[@]}" \
  "$@"
