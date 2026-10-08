#!/usr/bin/env bash
# Compatibility entry: keep existing map/profile defaults in canonical bringup.
set -eo pipefail
if [[ $# -gt 0 ]]; then
  exec env MODE=nav MAP="$1" /bin/bash /home/sunrise/luka_ws/src/system/bringup/restart_nav_reset.sh
fi
exec /bin/bash /home/sunrise/luka_ws/src/system/bringup/start_nx_navigation.sh
