#!/usr/bin/env bash
set -euo pipefail

# Read-only Xiaozhi/Luka integration preflight.
# Does not enable following/navigation and does not publish Twist.

BASE="${LUKA_ASSISTANT_BASE:-http://127.0.0.1:8503}"
WORKSPACE="${LUKA_WS:-/home/sunrise/luka_ws}"
CONFIG="${MCP_CONFIG:-$WORKSPACE/system/xiaozhi/mcp_config.luka.json}"

python3 - "$BASE" "$CONFIG" <<'PY'
import json
import pathlib
import sys
import urllib.request

base=sys.argv[1].rstrip("/")
config=pathlib.Path(sys.argv[2])

with config.open(encoding="utf-8") as f:
    cfg=json.load(f)
server=(cfg.get("mcpServers") or {}).get("luka-robot") or {}
assert server.get("type") == "stdio", "luka-robot MCP transport must be stdio"
assert "LUKA_XIAOZHI_ALLOW_MOTION" not in (server.get("env") or {}), (
    "MCP config must not override the operator motion gate"
)

with urllib.request.urlopen(base+"/api/assistant/tools", timeout=4) as response:
    catalog=json.load(response)

tools=catalog.get("tools") or {}
generation=catalog.get("generation")
required=(
    "robot_status",
    "destinations",
    "follow_status",
    "follow_start",
    "follow_stop",
    "navigate",
    "cancel_all",
)
missing=[name for name in required if name not in tools]
if missing:
    raise SystemExit("missing assistant tools: "+", ".join(missing))
if type(generation) is not int:
    raise SystemExit("assistant generation token missing")

# Read-only API calls only.
def post(tool, source):
    body=json.dumps({
        "tool":tool,
        "arguments":{},
        "source":source,
    },ensure_ascii=False).encode("utf-8")
    req=urllib.request.Request(
        base+"/api/assistant/execute",
        data=body,
        headers={"Content-Type":"application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as response:
        return json.load(response)

for tool,source in (
    ("robot_status","查询小车状态"),
    ("follow_status","查询跟随状态"),
    ("localization_status","查询定位状态"),
    ("functions_status","查询服务状态"),
):
    result=post(tool,source)
    if result.get("ok") is not True:
        raise SystemExit(f"{tool} failed: {result}")

print("OK: Luka assistant tool catalog and read-only calls")
print("OK: MCP stdio config")
print("OK: no motion command was sent")
PY
