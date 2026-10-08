#!/usr/bin/env bash
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/_source_ws.sh"

if [[ $# -lt 1 ]]; then
  echo "用法: $0 '去厨房'" >&2
  exit 1
fi

TEXT="$1"
python3 - "$TEXT" <<'PY'
import sys
import time
import rclpy
from std_msgs.msg import String

text = sys.argv[1]
rclpy.init()
node = rclpy.create_node('llm_command_pub')
pub = node.create_publisher(String, '/llm_command', 10)
msg = String()
msg.data = text
# Wait for subscriber discovery (up to 5s), then publish and stay alive
# a moment so the message is actually delivered.
deadline = time.monotonic() + 5.0
while time.monotonic() < deadline:
    if pub.get_subscription_count() > 0:
        break
    rclpy.spin_once(node, timeout_sec=0.1)
pub.publish(msg)
end = time.monotonic() + 1.0
while time.monotonic() < end:
    rclpy.spin_once(node, timeout_sec=0.1)
node.destroy_node()
rclpy.shutdown()
print(f'sent: {text}')
PY
