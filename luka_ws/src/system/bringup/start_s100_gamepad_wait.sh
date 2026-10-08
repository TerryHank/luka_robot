#!/bin/bash
set -eo pipefail
echo 'Waiting for gamepad receiver at /dev/input/js0'
until [ -c /dev/input/js0 ]; do
  sleep 2
done
exec /bin/bash /home/sunrise/luka_ws/system/bringup/start_nx_gamepad.sh
