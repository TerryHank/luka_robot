"""Compatibility alias for the Recovery behavior."""
from pathlib import Path as _SourcePath
import sys as _source_sys
_source_root = _SourcePath(__file__).resolve().parents[2]
for _package_path in ['behavior/luka_behaviors']:
    _source_dir = _source_root / _package_path
    if _source_dir.is_dir() and str(_source_dir) not in _source_sys.path:
        _source_sys.path.insert(0, str(_source_dir))
from luka_behaviors import recovery as _implementation
_source_sys.modules[__name__]=_implementation
