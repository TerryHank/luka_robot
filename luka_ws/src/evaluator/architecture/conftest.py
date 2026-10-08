import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
for package in ('system/luka_capabilities','behavior/luka_behaviors','mission/luka_mission',
                'control/luka_motion_gateway','control/luka_base_gate'):
    sys.path.insert(0,str(ROOT/package))
