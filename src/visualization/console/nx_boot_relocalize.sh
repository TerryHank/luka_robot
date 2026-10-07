#!/bin/bash
set -euo pipefail
dashboard=http://127.0.0.1:8503
for _ in $(seq 1 90); do
  if /usr/bin/curl -fsS --max-time 2 "$dashboard/api/functions/status" |
     /usr/bin/python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if d.get("health",{}).get("navigation_data_ready") else 1)' 2>/dev/null; then
    /usr/bin/curl -fsS --max-time 6 -X POST -H 'Content-Type: application/json' -d '{}' "$dashboard/api/localization/auto"
    exit 0
  fi
  sleep 1
done
echo '定位所需数据未在 90 秒内就绪，跳过本次自动重定位' >&2
exit 1
