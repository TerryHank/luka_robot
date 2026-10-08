#!/bin/sh
set -eu
was_active=0
if systemctl is-active --quiet spatial-memory.service; then was_active=1; fi
restore() {
    if [ "$was_active" -eq 1 ]; then
        systemctl start spatial-memory.service
        echo ORIGINAL_SERVICE_RESTORED
    fi
}
trap restore EXIT
if [ "$was_active" -eq 1 ]; then systemctl stop spatial-memory.service; fi
runuser -u nvidia -- /usr/bin/python3 /home/sunrise/luka_ws/perception/locateanything_trial_20260907/supervise.py
