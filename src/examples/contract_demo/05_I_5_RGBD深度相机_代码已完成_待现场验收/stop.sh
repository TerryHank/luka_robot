#!/usr/bin/env bash
set -eo pipefail
HERE="$(cd -- "$(dirname -- "$0")" && pwd)"
WS="$(cd -- "$HERE/../../../.." && pwd)"
source "$WS/src/system/environment.bash"
exec python3 "$HERE/../_shared/stop_launch.py" camera
