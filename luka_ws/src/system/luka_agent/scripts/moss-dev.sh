#!/usr/bin/env bash
set -euo pipefail
base=/home/sunrise/luka_ws/src/system/luka_agent
node=/home/sunrise/luka_data/runtime/toolchains/node-v24.18.0-linux-arm64/bin/node
runtime=/home/sunrise/luka_data/runtime/agent-dev
mkdir -p "$runtime"
# This separate developer entry has no connection to the voice consumer.
# Keep the unconfigured developer entry read-only during candidate validation.
exec "$node" "$base/vendor/moss/dist/cli.js" --read-only --cd "$runtime" "$@"
