#!/usr/bin/env bash
# Shared workspace sourcing for nav_llm_agent scripts (WSL sim or RK3588 board).
# shellcheck disable=SC1091

set +u
source /opt/ros/humble/setup.bash

_pick_ws() {
  if [[ -n "${ROS_WS:-}" && -f "${ROS_WS}/install/setup.bash" ]]; then
    echo "${ROS_WS}"
    return
  fi
  local home="${ROS_USER_HOME:-${HOME}}"
  local candidate
  for candidate in \
      "${home}/ddsm_car_ws" \
      "${home}/ros2_ws" \
      "/home/sunrise/luka_ws" \
      "/home/yuxi/ros2_ws"; do
    if [[ -f "${candidate}/install/setup.bash" ]]; then
      echo "${candidate}"
      return
    fi
  done
  return 1
}

ROS_WS="$(_pick_ws || true)"
if [[ -n "${ROS_WS}" && -f "${ROS_WS}/install/setup.bash" ]]; then
  # shellcheck disable=SC1090
  source "${ROS_WS}/install/setup.bash"
  export ROS_WS
fi

# Board (RK3588): match the nav stack's DDS implementation (cyclonedds).
# Cross-vendor (fastrtps <-> cyclonedds) mangles larger action goal messages,
# so agent/scripts must use the same RMW as restart_nav_reset.sh.
if [[ "$(uname -m)" == "aarch64" ]] || [[ "${ROS_WS:-}" == *ddsm_car_ws* ]]; then
  export RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_cyclonedds_cpp}"
  if [[ "${ROS_WS:-}" == "/home/sunrise/luka_ws" ]]; then
    export CYCLONEDDS_URI="${CYCLONEDDS_URI:-file://${ROS_WS}/src/common/config/cyclonedds_nav2.xml}"
  else
  export CYCLONEDDS_URI="${CYCLONEDDS_URI:-file://${ROS_WS}/config/cyclonedds_nav2.xml}"
  fi
fi
set -u
