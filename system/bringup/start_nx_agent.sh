#!/bin/bash
set -eo pipefail
source /opt/ros/humble/setup.bash
source /home/sunrise/luka_ws/install/setup.bash
export ROS_DOMAIN_ID=87 ROS_LOCALHOST_ONLY=1 RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI=file:///home/sunrise/luka_ws/common/config/cyclonedds_offline.xml
pids=()
cleanup() {
  set +e
  for pid in "${pids[@]:-}"; do kill -TERM "$pid" 2>/dev/null || true; done
  for pid in "${pids[@]:-}"; do wait "$pid" 2>/dev/null || true; done
}
trap cleanup EXIT INT TERM

ros2 run nav_llm_agent interaction_gateway --ros-args \
 -p input_topic:=/luka/interaction/agent_input \
 -p output_topic:=/llm_voice_command &
pids+=("$!")

ros2 run nav_llm_agent agent_node --ros-args \
 -p dry_run:=false \
 -p ollama_url:=http://127.0.0.1:8092 -p model:=qwen3-4b-chat -p llm_api:=openai \
 -p chat_url:=http://127.0.0.1:8092 -p chat_model:=qwen3-4b-chat \
 -p chat_api_key_env:=NX_LOCAL_NO_API_KEY \
 -p timeout_sec:=60.0 -p max_tokens:=512 \
 -p capabilities_file:=/home/sunrise/luka_ws/system/nav_llm_agent/config/capabilities.yaml \
 -p waypoints_file:=/home/sunrise/luka_ws/system/nav_llm_agent/config/waypoints_rk3588.yaml \
 -p transfer_state_file:=/home/sunrise/luka_ws/common/config/nx_dryrun_transfer_state.yaml \
 -p current_floor_id:=floor_4 &
pids+=("$!")

wait -n
