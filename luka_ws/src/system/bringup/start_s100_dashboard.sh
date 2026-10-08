#!/usr/bin/env bash
set -euo pipefail
export LUKA_SOFTWARE_ONLY=1
exec /bin/bash /home/sunrise/luka_ws/system/bringup/start_nx_dashboard.sh
