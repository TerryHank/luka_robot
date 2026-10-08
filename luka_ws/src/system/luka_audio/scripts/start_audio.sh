#!/usr/bin/env bash
set -eo pipefail
source /home/sunrise/luka_ws/src/system/environment.bash
base=/home/sunrise/luka_ws/src/system/luka_audio
export LUKA_AUDIO_BIN=/home/sunrise/luka_ws/install/luka_audio/lib/luka_audio
serial_args=()
if [ -n "${LUKA_AUDIO_SERIAL:-}" ]; then
  serial_args=(-p serial_device:="$LUKA_AUDIO_SERIAL")
fi
exec "$base/audio_venv/bin/python" -m luka_audio.gateway --ros-args \
  -p microphone:="${NX_MIC:-hw:CARD=XFMDPV0018,DEV=0}" \
  -p speaker:="${NX_SPEAKER:-plughw:CARD=Device,DEV=0}" \
  -p frontend:="${LUKA_AUDIO_FRONTEND:-xfm_adb}" \
  -p backend_mode:="${LUKA_AUDIO_MODE:-auto}" \
  -p dispatch_commands:="${LUKA_VOICE_DISPATCH_COMMANDS:-false}" "${serial_args[@]}" "$@"
