#!/usr/bin/env bash
set -euo pipefail

# Read-only L4 Voice Runtime inspection.
# This script does not publish /voice/control, does not call MCP tools, and does
# not send Nav2/Twist/DDSM commands.

ROOT="${1:-/home/sunrise/luka_ws}"
OUT="${2:-$ROOT/docs/voice_runtime/live}"
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

if grep -qx "/voice_gateway" "$DEST/nodes.txt"; then
  ok "voice_gateway node present"
else
  bad "voice_gateway node missing"
fi

if grep -q "^/voice/runtime " "$DEST/topics.txt"; then
  ok "/voice/runtime topic present"
else
  bad "/voice/runtime topic missing"
fi

for param in duplex_mode aec_provider barge_in_enabled continuous_dialogue; do
  ros2 param get /voice_gateway "$param" > "$DEST/param_$param.txt" 2>&1 || true
done

timeout 4s ros2 topic echo /voice/runtime --once > "$DEST/runtime.txt" 2>&1 || true

if grep -q "\"state\"" "$DEST/runtime.txt"; then
  ok "structured runtime snapshot received"
else
  bad "no structured runtime snapshot received"
fi

duplex="$(sed -n 's/^String value is: //p' "$DEST/param_duplex_mode.txt" | tail -1)"
aec="$(sed -n 's/^String value is: //p' "$DEST/param_aec_provider.txt" | tail -1)"

if [ "$duplex" = "aec_full_duplex" ] && { [ -z "$aec" ] || [ "$aec" = "none" ] || [ "$aec" = "disabled" ]; }; then
  bad "aec_full_duplex is selected without a named AEC provider"
else
  ok "duplex/AEC policy is internally consistent"
fi

cat >> "$DEST/result.txt" <<'EOF'

NO-MOTION ASSERTION:
- no /voice/control message was published;
- no MCP tool was called;
- no Nav2 goal, Twist or DDSM command was sent.

PHYSICAL FULL-DUPLEX GATES (not checked by this script):
[ ] capture source is genuinely echo-cancelled;
[ ] local TTS does not false-trigger KWS/VAD;
[ ] speaking -> listening barge-in cancels audio promptly;
[ ] VAD cache retains the first user syllable;
[ ] 30+ minute continuous dialogue shows no runaway queue/memory growth.
EOF

echo "L4 voice read-only report: $DEST"
exit "$fail"
