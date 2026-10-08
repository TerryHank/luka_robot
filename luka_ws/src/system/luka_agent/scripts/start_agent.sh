#!/usr/bin/env bash
set -euo pipefail
base=/home/sunrise/luka_ws/src/system/luka_agent
exec /home/sunrise/luka_data/runtime/toolchains/node-v24.18.0-linux-arm64/bin/node "$base/src/service.mjs"
