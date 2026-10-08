#!/usr/bin/env bash
set -eo pipefail
source /home/sunrise/luka_ws/system/environment.bash
exec /usr/bin/python3 /home/sunrise/luka_ws/perception/locateanything_trial_20260907/live_app.py
