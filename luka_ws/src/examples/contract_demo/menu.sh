#!/usr/bin/env bash
set -eo pipefail
HERE="$(cd -- "$(dirname -- "$0")" && pwd)"
WS="$(cd -- "$HERE/../../.." && pwd)"
source "$WS/src/system/environment.bash"
python3 "$HERE/_shared/runner.py" --list
read -r -p '输入合同演示序号01至27：' number
exec python3 "$HERE/_shared/runner.py" --item "$number"
