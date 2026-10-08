#!/usr/bin/env bash
set -eo pipefail
HERE="$(cd -- "$(dirname -- "$0")" && pwd)"
exec python3 "$HERE/../_shared/stop_launch.py" drive_odom
