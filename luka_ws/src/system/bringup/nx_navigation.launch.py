"""Compatibility launch: canonical navigation plus the complete safety chain."""
from pathlib import Path as _SourcePath
import sys as _source_sys
_source_root = _SourcePath(__file__).resolve().parents[2]
for _package_path in ['system/luka_bringup']:
    _source_dir = _source_root / _package_path
    if _source_dir.is_dir() and str(_source_dir) not in _source_sys.path:
        _source_sys.path.insert(0, str(_source_dir))
from launch import LaunchDescription
from luka_bringup.navigation import navigation_actions,safety_actions

def generate_launch_description():
 return LaunchDescription(safety_actions()+navigation_actions())
