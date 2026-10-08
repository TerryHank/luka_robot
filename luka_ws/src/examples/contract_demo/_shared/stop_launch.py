#!/usr/bin/env python3
"""Signal only the recorded foreground launch process, not system services."""
import json
import os
from pathlib import Path
import signal
import sys
import time

HERE = Path(__file__).resolve().parent
WS = HERE.parents[3]
if len(sys.argv) != 2 or sys.argv[1] not in ('drive_odom', 'imu_axes', 'avoidance', 'business', 'camera', 'diagnostics', 'face', 'home', 'interfaces', 'layers', 'lidar', 'localization', 'map', 'navigation', 'slam', 'smoothing', 'state_machine', 'voice'):
    raise SystemExit("Unknown launch demonstration group")
path = WS.parent / "luka_data/recordings/contract_demo" / (sys.argv[1] + ".pid.json")
if not path.exists():
    print("No running launch recorded")
    raise SystemExit(0)
record = json.loads(path.read_text())
pid = int(record["pid"])
proc = Path(f"/proc/{pid}")
if not proc.exists():
    path.unlink()
    raise SystemExit(0)
assert proc.joinpath("stat").read_text().split()[21] == record["start_ticks"], "PID reused"
assert record.get("launch_token", record["launch_file"]).encode() in (
    proc.joinpath("cmdline").read_bytes().split(b"\0")), "Unexpected process"
os.kill(pid, signal.SIGINT)
for _ in range(200):
    if not proc.exists() or not path.exists():
        print("Launch shutdown confirmed; reused production services remain running")
        break
    time.sleep(.1)
else:
    raise SystemExit("Shutdown not confirmed within 20s; inspect the launch terminal")
