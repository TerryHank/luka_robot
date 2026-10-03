"""Fail closed before sending a page-selected observation to ROS."""
import math


def selected_observation(state, request_age=0.0):
    if not state.get('active') or state.get('loading') or state.get('error'):
        return None, 'monitor_unavailable'
    age = state.get('camera_age')
    if age is None or not math.isfinite(age) or not 0 <= age + request_age <= .5:
        return None, 'stale_frame'
    ident = state.get('selected_track_id')
    if ident is None:
        return None, 'unselected'
    rows = [r for r in state.get('tracks', []) if r.get('track_id') == ident]
    if len(rows) != 1:
        return None, 'selected_missing'
    row = rows[0]
    if row.get('visible') is False or row.get('association_ambiguous') or row.get('observation_strength') != 'strong':
        return None, 'selected_ambiguous_or_weak'
    geo = row.get('depth_diagnostic') or {}
    xyz = geo.get('position_optical_m', [])
    sizes = [geo.get('width_m', 0), geo.get('height_m', 0)]
    if (not row.get('depth_valid') or geo.get('method') != 'seg_valid_trimmed_mean'
            or len(xyz) != 3 or not all(math.isfinite(v) for v in xyz + sizes)
            or min(xyz[2], *sizes) <= 0):
        return None, 'invalid_seg_depth'
    if row.get('confidence', 0) < .7 or sizes[0] < .3 or sizes[1] < .5:
        return None, 'official_target_filter'
    return row, 'selected_seg_depth_valid'
