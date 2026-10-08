#!/usr/bin/env bash
set -eo pipefail
source /home/sunrise/luka_ws/src/system/environment.bash
exec /home/sunrise/luka_ws/src/system/luka_audio/audio_venv/bin/python \
  /home/sunrise/luka_ws/install/luka_xiaozhi/lib/luka_xiaozhi/xiaozhi-in-rdk.py --ros-speech "$@"
