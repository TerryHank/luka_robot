#!/usr/bin/env bash
# One-shot dry_run agent on RK3588 using on-board Qwen2.5 (llama-server :8080).
set -eo pipefail
export ROS_WS="${ROS_WS:-/home/sunrise/luka_ws}"
export USE_SIM_TIME=false
export OLLAMA_URL="${OLLAMA_URL:-http://127.0.0.1:8080}"
export MODEL="${MODEL:-/home/nvidia/pan/Qwen2.5-1.5B/models/Qwen2.5-1.5B-Instruct-Q8_0.gguf}"
export LLM_API="${LLM_API:-openai}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "${SCRIPT_DIR}/start_agent.sh" dry_run:=true "$@"
