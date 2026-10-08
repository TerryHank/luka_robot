#!/usr/bin/env bash
# SLAM only; do not implicitly select autonomous exploration.
set -eo pipefail
exec env MODE=slam /bin/bash /home/sunrise/luka_ws/src/system/bringup/restart_nav_reset.sh
