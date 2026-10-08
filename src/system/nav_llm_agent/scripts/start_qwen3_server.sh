#!/usr/bin/env bash
set -eo pipefail

USER_HOME="${ROS_USER_HOME:-/home/yuxi}"
if [[ ! -d "${USER_HOME}/qwen3-serve" && -d "${HOME}/qwen3-serve" ]]; then
  USER_HOME="${HOME}"
fi

MODEL_DIR="${QWEN3_MODEL_DIR:-${USER_HOME}/qwen3-serve/model}"
VENV_PY="${QWEN3_PYTHON:-${USER_HOME}/qwen3-serve/.venv/bin/python}"
HOST="${OLLAMA_HOST:-127.0.0.1}"
PORT="${OLLAMA_PORT:-11434}"
SCRIPT="${USER_HOME}/ros2_ws/src/nav_llm_agent/scripts/serve_qwen3.py"

if [[ ! -x "${VENV_PY}" ]]; then
  echo "找不到 Python: ${VENV_PY}" >&2
  exit 1
fi
if [[ ! -f "${MODEL_DIR}/config.json" ]]; then
  echo "找不到模型: ${MODEL_DIR}" >&2
  echo "请先下载 Qwen/Qwen3-1.7B 到该目录。" >&2
  exit 1
fi

echo "=============================================="
echo "  Qwen3-1.7B 本地服务（Ollama /api/chat 兼容）"
echo "  模型: ${MODEL_DIR}"
echo "  地址: http://${HOST}:${PORT}"
echo "=============================================="

exec env PYTHONUNBUFFERED=1 "${VENV_PY}" "${SCRIPT}" --model-path "${MODEL_DIR}" --host "${HOST}" --port "${PORT}"
