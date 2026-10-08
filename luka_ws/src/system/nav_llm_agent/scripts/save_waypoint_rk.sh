#!/usr/bin/env bash
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/_source_ws.sh"

echo "在 RViz 用 Publish Point 点地图后，本命令会提示输入名称。"
echo "请先启动: bash ${SCRIPT_DIR}/start_agent.sh"
echo "=============================================="
exec ros2 run nav_llm_agent save_waypoint "$@"
