#!/usr/bin/env bash
set -eo pipefail
HERE="$(cd -- "$(dirname -- "$0")" && pwd)"
WS="$(cd -- "$HERE/../../../.." && pwd)"
source "$WS/src/system/environment.bash"
case "$1" in
  odom) exec python3 "$WS/src/visualization/console/nx_readonly_odom.py";;
  ekf|deskew) exec ros2 launch "$HERE/analysis.launch.py" "mode:=$1";;
  localization) exec ros2 launch "$HERE/localization.launch.py";;
  slam) exec ros2 launch "$HERE/slam.launch.py";;
  business) exec ros2 launch "$HERE/business.launch.py";;
  face) exec /usr/bin/python3 "$HERE/face_monitor.py";;
  *) echo 'Unknown contract runtime' >&2; exit 2;;
esac
