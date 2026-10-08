#!/usr/bin/env bash
set -Eeuo pipefail

WS="${DDSM_WS:-/home/sunrise/luka_ws}"
VENV="${ROBOT_TUNING_VENV:-$WS/.venv_robot_tuning}"
PORT="${ROBOT_TUNING_PORT:-8501}"

exec "$VENV/bin/streamlit" run "$WS/system/runtime/tools/robot_tuning_ui.py" \
  --server.address 0.0.0.0 \
  --server.port "$PORT" \
  --server.headless true \
  --browser.gatherUsageStats false
