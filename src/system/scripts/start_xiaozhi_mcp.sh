#!/usr/bin/env bash
set -euo pipefail

if [ -z "${MCP_ENDPOINT:-}" ]; then
  echo "MCP_ENDPOINT is required. Use the endpoint provided by your Xiaozhi service." >&2
  exit 2
fi

WORKSPACE="${LUKA_WS:-/home/sunrise/luka_ws}"
export MCP_CONFIG="${MCP_CONFIG:-$WORKSPACE/system/xiaozhi/mcp_config.luka.json}"

if [ -n "${XIAOZHI_RDK_ROOT:-}" ]; then
  ROOT="$XIAOZHI_RDK_ROOT"
elif [ -f /home/sunrise/xiaozhi-in-rdk/mcp_pipe.py ]; then
  ROOT=/home/sunrise/xiaozhi-in-rdk
elif [ -f /opt/xiaozhi-in-rdk/mcp_pipe.py ]; then
  ROOT=/opt/xiaozhi-in-rdk
else
  echo "xiaozhi-in-rdk not found. Set XIAOZHI_RDK_ROOT to the pinned checkout." >&2
  exit 3
fi

if [ ! -f "$ROOT/mcp_pipe.py" ]; then
  echo "Missing $ROOT/mcp_pipe.py" >&2
  exit 4
fi

echo "Xiaozhi MCP bridge:"
echo "  upstream: $ROOT"
echo "  config:   $MCP_CONFIG"
echo "  motion:   ${LUKA_XIAOZHI_ALLOW_MOTION:-0} (config default is 0)"
exec python3 "$ROOT/mcp_pipe.py"
