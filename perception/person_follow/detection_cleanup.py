"""Consolidate a narrowly defined whole-body / upper-body detector duplicate.

This is an observation cleanup, not person re-identification.  It never merges
ordinary overlapping, similar-size people.  Missing depth needs exactly one
detected face as additional evidence; face counting does not assert identity.
The caller remains responsible for ambiguous tracking and stale-frame handling.
"""
from __future__ import annotations

import copy
import math
from numbers import Integral


def _bbox(row):
    try:
        box = tuple(float(x) for x in row.get("bbox", ()))
    except (TypeError, ValueError):
        return None
    if (len(box) != 4 or not all(math.isfinite(x) for x in box) or
            box[2] <= box[0] or box[3] <= box[1]):
        return None
    return box


def _area(box):
    return (box[2] - box[0]) * (box[3] - box[1])


def _iou(a, b):
    width = max(0., min(a[2], b[2]) - max(a[0], b[0]))
    height = max(0., min(a[3], b[3]) - max(a[1], b[1]))
    intersection = width * height
    return intersection / max(1e-8, _area(a) + _area(b) - intersection)


def _depth(row):
    # Explicitly invalid geometry must never supply evidence via a stale field.
    if row.get("depth_valid") is False:
        return None
    try:
        value = float(row.get("depth_m"))
    except (ValueError, TypeError):
        return None
    return value if math.isfinite(value) and value > 0 else None


def _geometry_candidate(large, small, frame_size=None, preferred_bbox=None):
    small_area, large_area = _area(small), _area(large)
    ratio = small_area / large_area
    if not .15 <= ratio <= .80:
        return False
    overlap_w = max(0., min(large[2], small[2]) - max(large[0], small[0]))
    overlap_h = max(0., min(large[3], small[3]) - max(large[1], small[1]))
    if overlap_w * overlap_h / small_area < .94:
        return False
    small_w, small_h = small[2] - small[0], small[3] - small[1]
    top_offset = abs(large[1] - small[1])
    near_top = top_offset <= .10 * small_h
    center_offset = abs((large[0] + large[2] - small[0] - small[2]) / 2)
    if ratio >= .25 and near_top and center_offset <= .20 * small_w:
        return True
    # A close seated person can produce a frame-wide body box and a nested
    # upper-body box off to one side. Only consider that shape when the larger
    # box covers most of a known camera frame. Face/depth checks still apply.
    prior = _bbox({'bbox': preferred_bbox}) if preferred_bbox is not None else None
    if frame_size is None or prior is None:
        return False
    frame_w, frame_h = frame_size
    large_w, large_h = large[2] - large[0], large[3] - large[1]
    return (frame_w > 0 and frame_h > 0 and
            _iou(large, prior) >= .55 and _iou(small, prior) < .45 and
            large_w >= .60 * frame_w and _area(large) >= .45 * frame_w * frame_h and
            small_area / large_area <= .38 and center_offset <= .28 * large_w and
            (near_top or (large[1] <= .02 * frame_h and top_offset <= .20 * frame_h)))


def consolidate_people(detections, face_count=None, frame_size=None, preferred_bbox=None):
    """Return detached detection dictionaries with safe nested duplicates removed.

    ``face_count(union_bbox)`` is an optional callable returning a nonnegative
    integer, or ``None`` if unknown.  It is invoked only for geometry/depth
    candidate pairs.  Two or more faces always forbid a merge; when either
    detection lacks valid depth, exactly one face is required.  A callback
    error skips that pair.  At most the first eight input detections are
    considered (at most 28 candidate pairs); extra entries remain unchanged.

    The broader near-camera case additionally requires ``preferred_bbox`` from
    a fresh, strong, explicitly selected body track. This is only duplicate
    cleanup, not proof of the person's identity.

    The larger detection retains its geometry and all its depth/bearing fields.
    Only confidence is raised to the group's maximum. ``duplicate_boxes`` counts
    the additional boxes suppressed, so consolidating a pair produces 1.
    """
    rows = [copy.deepcopy(row) for row in detections]
    boxes = [_bbox(row) for row in rows[:8]]
    order = sorted((i for i, box in enumerate(boxes) if box is not None),
                   key=lambda i: (-_area(boxes[i]), i))
    suppressed = set()
    face_cache = {}
    for offset, large_i in enumerate(order):
        if large_i in suppressed:
            continue
        large = boxes[large_i]
        large_d = _depth(rows[large_i])
        for small_i in order[offset + 1:]:
            if small_i in suppressed:
                continue
            small = boxes[small_i]
            if not _geometry_candidate(large, small, frame_size, preferred_bbox):
                continue
            small_d = _depth(rows[small_i])
            both_depth = large_d is not None and small_d is not None
            if both_depth and abs(large_d - small_d) > .25:
                continue
            count = None
            if face_count is not None:
                union = (min(large[0], small[0]), min(large[1], small[1]),
                         max(large[2], small[2]), max(large[3], small[3]))
                if union not in face_cache:
                    try:
                        value = face_count(list(union))
                        valid_count = isinstance(value, Integral) and not isinstance(value, bool) and value >= 0
                        face_cache[union] = (True, int(value) if valid_count else None)
                    except Exception:
                        face_cache[union] = (False, None)
                available, count = face_cache[union]
                if not available:
                    continue
            if count is not None and count > 1:
                continue
            small_width = small[2] - small[0]
            off_axis = abs((large[0] + large[2] - small[0] - small[2]) / 2) > .20 * small_width
            if off_axis and count != 1:
                continue
            if not both_depth and count != 1:
                continue
            suppressed.add(small_i)
            rows[large_i]["duplicate_consolidated"] = True
            rows[large_i]["duplicate_boxes"] = rows[large_i].get("duplicate_boxes", 0) + 1
            scores = []
            for row in (rows[large_i], rows[small_i]):
                try:
                    score = float(row.get("confidence"))
                    if math.isfinite(score):
                        scores.append(score)
                except (TypeError, ValueError):
                    pass
            if scores:
                rows[large_i]["confidence"] = max(scores)
    return [row for i, row in enumerate(rows) if i not in suppressed]
