"""Compatibility alias for pure voice routing."""
from pathlib import Path as _SourcePath
import sys as _source_sys
_source_root = _SourcePath(__file__).resolve().parents[2]
for _package_path in ['system/luka_capabilities']:
    _source_dir = _source_root / _package_path
    if _source_dir.is_dir() and str(_source_dir) not in _source_sys.path:
        _source_sys.path.insert(0, str(_source_dir))
from luka_capabilities import voice_commands as _implementation
_source_sys.modules[__name__]=_implementation
