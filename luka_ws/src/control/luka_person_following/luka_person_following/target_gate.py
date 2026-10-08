"""Pure fail-closed target selection for ROS-native person observations."""
from __future__ import annotations

import math


def _finite(value):
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if math.isfinite(value) else None


def selected_target(rows, selected_id, age_s, auto_select_first_person=False):
    """Return (row, reason, effective_id) without any ROS dependency."""
    age_s = _finite(age_s)
    if age_s is None or age_s < 0 or age_s > 0.5:
        return None, "stale_frame", selected_id

    people = [row for row in (rows or []) if row.get("class", "person") == "person"]
    effective_id = selected_id
    if effective_id is None or int(effective_id) < 0:
        if auto_select_first_person and len(people) == 1:
            effective_id = people[0].get("track_id")
        else:
            return None, "unselected", None

    matches = [row for row in people if int(row.get("track_id", -1)) == int(effective_id)]
    if len(matches) != 1:
        return None, "selected_missing", effective_id
    row = matches[0]

    if (row.get("visible") is False
            or row.get("association_ambiguous") is True
            or row.get("observation_strength") != "strong"):
        return None, "selected_ambiguous_or_weak", effective_id

    if row.get("seg_depth_trimmed_mean") is not True:
        return None, "invalid_seg_depth_method", effective_id
    if row.get("depth_valid") is not True:
        return None, "invalid_seg_depth", effective_id

    xyz = row.get("position_optical_m")
    width = _finite(row.get("width_m"))
    height = _finite(row.get("height_m"))
    if not isinstance(xyz, (list, tuple)) or len(xyz) != 3:
        return None, "invalid_seg_depth", effective_id
    xyz = [_finite(value) for value in xyz]
    if any(value is None for value in xyz):
        return None, "invalid_seg_depth", effective_id
    if xyz[2] <= 0 or width is None or height is None or width <= 0 or height <= 0:
        return None, "invalid_seg_depth", effective_id

    confidence = _finite(row.get("confidence"))
    if confidence is None or confidence < 0.5 or width < 0.3 or height < 0.5:
        return None, "official_target_filter", effective_id

    row = dict(row)
    row["position_optical_m"] = xyz
    row["width_m"] = width
    row["height_m"] = height
    row["confidence"] = confidence
    return row, "selected_seg_depth_valid", effective_id
