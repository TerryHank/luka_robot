#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-/home/sunrise/luka_ws}"
OUT="${2:-$ROOT/docs/interaction_runtime/live}"
DEST="$OUT/$(date +%Y%m%d_%H%M%S)_readonly"
mkdir -p "$DEST"

if [ -f /opt/tros/humble/setup.bash ]; then source /opt/tros/humble/setup.bash; fi
if [ -f /opt/ros/humble/setup.bash ]; then source /opt/ros/humble/setup.bash; fi
if [ -f "$ROOT/install/local_setup.bash" ]; then source "$ROOT/install/local_setup.bash"; fi

fail=0
ok(){ echo "OK: $*" | tee -a "$DEST/result.txt"; }
bad(){ echo "FAIL: $*" | tee -a "$DEST/result.txt"; fail=1; }

ros2 node list > "$DEST/nodes.txt" 2>&1 || true
ros2 topic list -t > "$DEST/topics.txt" 2>&1 || true

for node in /interaction_agent_gateway /interaction_platform_status /nav_llm_agent; do
  grep -qx "$node" "$DEST/nodes.txt" && ok "$node present" || bad "$node missing"
done

if grep -Eq '^/(voice_gateway|drobotics_voice_suite_bridge)$' "$DEST/nodes.txt"; then
  ok "one supported voice runtime is present"
else
  bad "no supported voice runtime node found"
fi

for topic in /voice/runtime /luka/interaction/gateway_status /luka/interaction/platform_status; do
  if grep -q "^$topic " "$DEST/topics.txt"; then
    ok "$topic present"
  else
    bad "$topic missing"
  fi
done

timeout 4s ros2 topic echo /luka/interaction/platform_status --once   > "$DEST/platform_status.txt" 2>&1 || true
if grep -q 'luka.interaction.platform_status.v1' "$DEST/platform_status.txt"; then
  ok "platform status snapshot received"
else
  bad "platform status snapshot unavailable"
fi

if command -v pactl >/dev/null 2>&1; then
  pactl info > "$DEST/pactl_info.txt" 2>&1 || true
  pactl list short sources > "$DEST/pulse_sources.txt" 2>&1 || true
  pactl list short sinks > "$DEST/pulse_sinks.txt" 2>&1 || true
fi

runtime_dir="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/luka"
if [ -f "$runtime_dir/xiaozhi_mode" ]; then
  cp "$runtime_dir/xiaozhi_mode" "$DEST/xiaozhi_mode.txt"
else
  echo off > "$DEST/xiaozhi_mode.txt"
fi

cat >> "$DEST/result.txt" <<'EOF'

READ-ONLY ASSERTION:
- no message was published to /luka/interaction/agent_input;
- no MCP tool was invoked;
- no Nav2 goal, Twist or DDSM command was sent.

PHYSICAL GATES NOT PROVEN HERE:
[ ] AEC convergence under the installed speaker/microphone geometry
[ ] near-end speech quality during TTS
[ ] false wake/VAD rate during TTS
[ ] barge-in latency and first-syllable retention
[ ] long-duration memory/queue stability
EOF

echo "L4 Interaction report: $DEST"
exit "$fail"
