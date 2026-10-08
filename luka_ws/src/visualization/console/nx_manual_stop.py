"""Compatibility entrypoint for the Base emergency stop tool."""
from pathlib import Path as _SourcePath
import sys as _source_sys
_source_root = _SourcePath(__file__).resolve().parents[2]
for _package_path in ['control/luka_base_gate', 'control/ddsm_car_control']:
    _source_dir = _source_root / _package_path
    if _source_dir.is_dir() and str(_source_dir) not in _source_sys.path:
        _source_sys.path.insert(0, str(_source_dir))
from luka_base_gate.manual_stop import main

if __name__=="__main__":main()
