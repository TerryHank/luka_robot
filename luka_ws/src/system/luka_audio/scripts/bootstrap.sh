#!/usr/bin/env bash
set -euo pipefail
base="$(cd -- "$(dirname -- "$0")/.." && pwd)"
models=/home/sunrise/luka_data/ml_models/audio
scratch="$(mktemp -d)"
trap 'rm -rf -- "$scratch"' EXIT
mkdir -p "$base/vendor" "$models/rdk_sensevoice" "$models/rdk_tts"
reference=/home/sunrise/luka_upstream/audio-sdk-reference
sdk=/home/sunrise/luka_ws/src/common/vendor
mkdir -p "$reference" "$sdk"
touch "$base/vendor/COLCON_IGNORE"
if [ ! -x "$base/audio_venv/bin/python" ]; then
  python3 -m venv --system-site-packages "$base/audio_venv"
fi
touch "$base/audio_venv/COLCON_IGNORE"
"$base/audio_venv/bin/python" -m pip install -r "$base/requirements.txt"
for spec in sensevoice_ros2:9200ec9a3b10ec558423a086f96d21ac3f862a7b hobot_tts:ecb8ace02a2ada04a8cb311d4eb697ad41ad91ee; do
  name="${spec%%:*}"
  revision="${spec#*:}"
  if [ ! -d "$reference/$name" ]; then
    curl -fL --retry 2 -o "$scratch/$name.tgz" "https://api.github.com/repos/D-Robotics/$name/tarball/$revision"
    mkdir -p "$reference/$name"
    tar -xzf "$scratch/$name.tgz" --strip-components=1 -C "$reference/$name"
  fi
done
if [ ! -d "$sdk/sensevoice_sdk" ]; then
  cp -a "$reference/sensevoice_ros2/include/sensevoice" "$sdk/sensevoice_sdk"
  cp "$reference/sensevoice_ros2/LICENSE" "$sdk/sensevoice_sdk/LICENSE"
fi
if [ ! -d "$sdk/wetts_sdk" ]; then
  cp -a "$reference/hobot_tts/wetts" "$sdk/wetts_sdk"
  cp "$reference/hobot_tts/LICENSE" "$sdk/wetts_sdk/LICENSE"
fi
if [ ! -f "$models/rdk_sensevoice/model.gguf" ]; then
  curl -fL --retry 2 -o "$scratch/model.gguf" https://www.modelscope.cn/models/lovemefan/SenseVoiceGGUF/resolve/master/sense-voice-small-q4_k.gguf
  echo "c8e7bf77acd860c5b83d2106da44aa7b985026ef4e7dbf5236c7f0f4001d9e9b  $scratch/model.gguf" | sha256sum -c -
  mv "$scratch/model.gguf" "$models/rdk_sensevoice/model.gguf"
fi
if [ ! -f "$models/rdk_tts/tts_model/tts.flags" ]; then
  curl -fL --retry 2 -o "$scratch/tts.tgz" https://archive.d-robotics.cc/tts-model/tts_model.tar.gz
  echo "56ee19a878f7488a0c110dcbd0124b97292a5ecc226450980162075f93156e9c  $scratch/tts.tgz" | sha256sum -c -
  tar -xzf "$scratch/tts.tgz" -C "$models/rdk_tts"
fi
echo "c8e7bf77acd860c5b83d2106da44aa7b985026ef4e7dbf5236c7f0f4001d9e9b  $models/rdk_sensevoice/model.gguf" | sha256sum -c -
echo 'Dependencies prepared. Build from ~/luka_ws with colcon --base-paths src.'
