from pathlib import Path
import sqlite3
import time
import numpy as np


def session_database(mode, source, data_root):
    if mode not in ('mapping', 'localization'):
        raise ValueError('mode must be mapping or localization')
    if mode == 'mapping' and source:
        raise ValueError('mapping always creates a new map; database_path is for localization')
    if mode == 'localization' and not Path(source).is_file():
        raise ValueError('localization requires an existing RTAB-Map database')
    folder = Path(data_root) / ('maps/visual_slam' if mode == 'mapping' else 'runtime/visual_slam') / str(time.time_ns())
    folder.mkdir(parents=True)
    target = folder / 'map.db'
    if mode == 'localization':
        with sqlite3.connect(Path(source).resolve().as_uri()+'?mode=ro', uri=True) as original:
            if original.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise ValueError('source map database is corrupt')
            if not original.execute("SELECT name FROM sqlite_master WHERE name='Node'").fetchone():
                raise ValueError('source is not an RTAB-Map database')
            with sqlite3.connect(target) as destination:
                original.backup(destination)
    return str(target)


def masked_depth(depth, mask):
    if depth.ndim != 2 or mask.shape != depth.shape or mask.dtype != np.uint8:
        raise ValueError('mask must be aligned mono8 with the same image dimensions')
    if depth.dtype not in (np.dtype('uint16'), np.dtype('float32')):
        raise ValueError('depth must be 16UC1 millimeters or 32FC1 meters')
    result = depth.copy()
    result[mask != 0] = 0 if depth.dtype == np.uint16 else np.nan
    return result


def validate_pair(stamps, frames, now, max_skew=.06, max_age=.6):
    if max(stamps)-min(stamps) > max_skew or now-min(stamps) > max_age or max(stamps)-now > .05:
        raise ValueError('stale or unsynchronized RGB-D/mask input')
    if not all(frames) or len(set(frames)) != 1:
        raise ValueError('RGB, registered depth, mask and calibration must share an optical frame')
