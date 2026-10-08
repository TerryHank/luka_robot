#!/bin/bash
# Hardware devices must be selected on NX; RK3588 ALSA card numbers are not portable.
set -eo pipefail
: "${NX_MIC:?请先用 arecord -L 查找麦克风，并设置 NX_MIC}"
: "${NX_SPEAKER:?请先用 aplay -L 查找扬声器，并设置 NX_SPEAKER}"
VOICE_BACKEND="${LUKA_VOICE_BACKEND:-legacy}"
if [[ "$VOICE_BACKEND" == "drobotics" ]]; then
  exec /bin/bash /home/sunrise/luka_ws/system/bringup/start_rdk_voice_suite.sh
fi
if [[ "$VOICE_BACKEND" != "legacy" ]]; then
  echo "Unsupported LUKA_VOICE_BACKEND=$VOICE_BACKEND (expected legacy|drobotics)" >&2
  exit 2
fi

source /opt/ros/humble/setup.bash
source /home/sunrise/luka_ws/install/setup.bash
export ROS_DOMAIN_ID=87 ROS_LOCALHOST_ONLY=1 RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI=file:///home/sunrise/luka_ws/common/config/cyclonedds_offline.xml
exec python3 /home/sunrise/luka_ws/system/runtime/tools/nx_voice_gateway.py --ros-args \
 -p audio_device:="$NX_MIC" -p speaker_device:="$NX_SPEAKER" \
 -p command_end_silence:=0.6 \
 --params-file "${NX_VOICE_STYLE:-/home/sunrise/luka_ws/common/config/nx_voice_style.yaml}"
