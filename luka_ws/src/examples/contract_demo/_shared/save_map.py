#!/usr/bin/env python3
"""Invoke the existing guarded map exporter without replacing navigation maps."""
from pathlib import Path
import subprocess
import sys

WS = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(WS / "src/visualization/console"))
from mapping_bundle import save_bundle


def run(arguments, timeout=25):
    p = subprocess.run(["ros2", *arguments], text=True, capture_output=True, timeout=timeout)
    return p.returncode == 0, p.stdout + p.stderr


ok, message = save_bundle(WS.parent / "luka_data/maps/contract_demo",
                          sys.argv[1] if len(sys.argv) > 1 else "contract_demo", run)
print(message)
raise SystemExit(0 if ok else 1)
