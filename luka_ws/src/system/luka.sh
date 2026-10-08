#!/usr/bin/env bash
set -euo pipefail
action=${1:-status}
workspace=${2:-ws}
mode=${3:-software}
case "$workspace" in
  ws) prefix=luka-ws; other=luka-s100;;
  s100) prefix=luka-s100; other=luka-ws;;
  *) echo 'Workspace must be ws or s100' >&2; exit 2;;
esac
software=("$prefix-dashboard.service" "$prefix-chat.service" "$prefix-agent.service" "$prefix-object-api.service")
hardware=("$prefix-hardware@sensors.service" "$prefix-hardware@manual_base.service" "$prefix-hardware@localization.service" "$prefix-hardware@navigation.service" "$prefix-hardware@voice.service")
vision=("$prefix-vision.service" "$prefix-people.service" "$prefix-yoloe26-live.service")
if [[ "$workspace" == ws ]]; then vision=("$prefix-orbbec-camera.service" "${vision[@]}"); fi
extras=("$prefix-boot-localize.service" "$prefix-nav-trace.service" "$prefix-wifi-recovery.timer" "$prefix-wifi-recovery.service" "$prefix-hardware@gamepad.service" "$prefix-hardware@sonar_ros.service")
all=("${software[@]}" "${hardware[@]}" "${vision[@]}" "${extras[@]}")
case "$action" in
  start)
    case "$mode" in software|stationary|full) ;; *) echo 'Mode must be software, stationary or full' >&2; exit 2;; esac
    # Either active or activating means the other stack still owns shared resources.
    conflicts=$(systemctl list-units --all --no-legend --plain "$other-*" | awk '$3 == "active" || $3 == "activating" {print $1}')
    if [[ -n "$conflicts" ]]; then
      printf 'Other workspace is running. Stop it first:\n%s\n' "$conflicts" >&2
      exit 1
    fi
    sudo -n systemctl start "${software[@]}"
    if [[ "$mode" == stationary ]]; then
      sudo -n systemctl start "${vision[@]}"
    fi
    if [[ "$mode" == full ]]; then
      echo 'Starting hardware and boot localization; automatic localization can rotate the robot.'
      sudo -n systemctl start "${hardware[@]}" "$prefix-nav-trace.service" "$prefix-wifi-recovery.timer"
      # Start localization before camera readiness can delay the people service.
      sudo -n systemctl start "$prefix-boot-localize.service"
      sudo -n systemctl start "${vision[@]}"
    fi
    systemctl list-units --all --no-pager "$prefix-*"
    ;;
  stop)
    if systemctl is-active --quiet "$prefix-dashboard.service" && systemctl is-active --quiet "$prefix-hardware@manual_base.service"; then
      python3 - <<'PY'
import json, urllib.request
try:
    req=urllib.request.Request('http://127.0.0.1:8503/api/assistant/execute',
        data=json.dumps({'tool':'cancel_all','arguments':{},'source':'停止导航巡航和找物'}).encode(),
        headers={'Content-Type':'application/json'},method='POST')
    with urllib.request.urlopen(req,timeout=8) as response:
        print(response.read().decode())
except Exception as exc:
    print('Cancellation API unavailable; stopping services:',exc)
PY
    fi
    sudo -n systemctl stop "${all[@]}"
    ;;
  status) systemctl list-units --all --no-pager "$prefix-*";;
  *) echo 'Usage: luka.sh {start|stop|status} {ws|s100} [software|stationary|full]' >&2; exit 2;;
esac
