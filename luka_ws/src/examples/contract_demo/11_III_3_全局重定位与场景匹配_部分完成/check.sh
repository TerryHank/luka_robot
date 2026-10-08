#!/usr/bin/env bash
set -eo pipefail
HERE="$(cd -- "$(dirname -- "$0")" && pwd)"
WS="$(cd -- "$HERE/../../../.." && pwd)"
source "$WS/src/system/environment.bash"
exec ros2 launch "$HERE/demo.launch.py" --show-args
