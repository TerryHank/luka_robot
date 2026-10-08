#!/usr/bin/env bash
set -euo pipefail

: "${NX_MIC:?请先用 arecord -L 查找麦克风，并设置 NX_MIC}"
: "${NX_SPEAKER:?请先用 aplay -L 查找扬声器，并设置 NX_SPEAKER}"

source /opt/tros/humble/setup.bash
source /home/sunrise/luka_ws/install/setup.bash
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-87}"
export ROS_LOCALHOST_ONLY="${ROS_LOCALHOST_ONLY:-1}"
export RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_cyclonedds_cpp}"
export CYCLONEDDS_URI="${CYCLONEDDS_URI:-file:///home/sunrise/luka_ws/common/config/cyclonedds_offline.xml}"

pids=()
cleanup() {
  set +e
  for pid in "${pids[@]:-}"; do kill -TERM "$pid" 2>/dev/null || true; done
  for pid in "${pids[@]:-}"; do wait "$pid" 2>/dev/null || true; done
}
trap cleanup EXIT INT TERM

# SenseVoice owns microphone capture in this backend. Do not start the legacy
# sherpa capture process at the same time.
ros2 launch sensevoice_ros2 sensevoice_ros2.launch.py   audio_asr_model:="${LUKA_SENSEVOICE_MODEL:-sense-voice-small-fp16.gguf}"   language:=zh   micphone_name:="$NX_MIC"   push_wakeup:=1   wakeup_name:="${LUKA_WAKE_WORD:-露卡}" &
pids+=("$!")

ros2 run hobot_tts hobot_tts --ros-args   -p topic_sub:=/tts_text   -p playback_device:="$NX_SPEAKER" &
pids+=("$!")

ros2 run nav_llm_agent voice_suite_bridge --ros-args   -p wake_word:="${LUKA_WAKE_WORD:-露卡}"   -p follow_up_timeout:="${LUKA_FOLLOW_UP_TIMEOUT:-12.0}" &
pids+=("$!")

wait -n "${pids[@]}"
