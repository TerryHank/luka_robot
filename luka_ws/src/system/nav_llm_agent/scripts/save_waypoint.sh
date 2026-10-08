#!/usr/bin/env bash
set -eo pipefail

set +u
source /opt/ros/humble/setup.bash
USER_HOME="${ROS_USER_HOME:-/home/yuxi}"
if [[ ! -f "${USER_HOME}/ros2_ws/install/setup.bash" && -f "${HOME}/ros2_ws/install/setup.bash" ]]; then
  USER_HOME="${HOME}"
fi
if [[ -f "${USER_HOME}/ros2_ws/install/setup.bash" ]]; then
  # shellcheck disable=SC1091
  source "${USER_HOME}/ros2_ws/install/setup.bash"
fi
set -u

echo "在 RViz 用 Publish Point 点地图后，本命令会提示输入名称。"
echo "请先启动: bash ~/ros2_ws/src/nav_llm_agent/scripts/start_agent.sh"
echo "=============================================="
exec ros2 run nav_llm_agent save_waypoint "$@"
