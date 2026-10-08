#!/usr/bin/env bash
set -euo pipefail
runtime_dir="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
file="$runtime_dir/luka/pulse_echo_cancel.module"
if [ ! -f "$file" ]; then
  exit 0
fi
module_id="$(cat "$file")"
if [ -n "$module_id" ]; then
  pactl unload-module "$module_id" 2>/dev/null || true
fi
rm -f "$file"
