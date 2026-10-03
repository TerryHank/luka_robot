"""Read-only stereo range from a pose-guided person torso.

The caller must associate pose and instance mask to the same selected person.
No result from this module alone authorizes motion.
"""
import math

import numpy as np


def pose_torso_geometry(depth_m, box, person_mask, points_xy, point_logits,
                        intrinsics, skew_s=0.):
    result = {'valid': False, 'reason': 'invalid_pose_torso',
              'source': 'stereo_pose_mask_torso'}
    depth, mask = np.asarray(depth_m), np.asarray(person_mask)
    points = np.asarray(points_xy, dtype=float)
    logits = np.asarray(point_logits, dtype=float).reshape(-1)
    if (depth.ndim != 2 or not np.issubdtype(depth.dtype, np.floating) or
            mask.ndim != 2 or points.shape != (17, 2) or logits.shape != (17,)):
        result['reason'] = 'invalid_depth_mask_or_pose'
        return result
    if not math.isfinite(skew_s) or abs(skew_s) > .12:
        result['reason'] = 'rgb_depth_not_synchronized'
        return result
    try:
        fx, cx = float(intrinsics['fx']), float(intrinsics['cx'])
        x1, y1, x2, y2 = map(int, box)
        if (not math.isfinite(fx) or fx <= 0 or not math.isfinite(cx) or
                not (0 <= x1 < x2 <= depth.shape[1] and
                     0 <= y1 < y2 <= depth.shape[0]) or
                mask.shape != (y2-y1, x2-x1)):
            raise ValueError()
    except (ValueError, TypeError, KeyError, OverflowError):
        result['reason'] = 'invalid_geometry_inputs'
        return result
    joint = points[[5, 6, 11, 12]]
    if not np.isfinite(joint).all() or not np.isfinite(logits[[5, 6, 11, 12]]).all():
        result['reason'] = 'invalid_pose_points'
        return result
    # Official model emits raw confidence logits. 1.1 is about 75% sigmoid.
    if np.any(logits[[5, 6, 11, 12]] < 1.1):
        result['reason'] = 'torso_keypoints_unreliable'
        return result
    shoulder = points[[5, 6]]
    hip = points[[11, 12]]
    shoulder_y, hip_y = float(shoulder[:, 1].mean()), float(hip[:, 1].mean())
    torso_h = hip_y-shoulder_y
    shoulder_w = float(np.ptp(shoulder[:, 0]))
    hip_w = float(np.ptp(hip[:, 0]))
    if (torso_h < 28 or shoulder_w < 18 or hip_w < 10 or
            shoulder_y < y1-.05*(y2-y1) or hip_y > y2+.05*(y2-y1) or
            np.min(joint[:, 0]) < x1-.05*(x2-x1) or
            np.max(joint[:, 0]) > x2+.05*(x2-x1)):
        result['reason'] = 'torso_pose_geometry_unreliable'
        return result
    rows = np.arange(y1, y2, dtype=float)[:, None]
    cols = np.arange(x1, x2, dtype=float)[None, :]
    t = np.clip((rows-shoulder_y)/torso_h, 0., 1.)
    left_shoulder, right_shoulder = sorted(shoulder[:, 0])
    left_hip, right_hip = sorted(hip[:, 0])
    left = (1-t)*left_shoulder+t*left_hip
    right = (1-t)*right_shoulder+t*right_hip
    width = right-left
    interior = ((rows >= shoulder_y+.15*torso_h) &
                (rows <= hip_y-.15*torso_h) &
                (cols >= left+.18*width) & (cols <= right-.18*width) &
                (mask > 0))
    patch = depth[y1:y2, x1:x2]
    selected = interior & np.isfinite(patch) & (patch >= .45) & (patch <= 4.)
    values = patch[selected]
    covered = int(interior.sum())
    result.update(valid_pixels=int(len(values)),
                  valid_fraction=round(len(values)/max(1, covered), 3))
    if covered < 300 or len(values) < 120 or len(values)/covered < .04:
        result['reason'] = 'insufficient_pose_torso_depth'
        return result
    counts, edges = np.histogram(values, bins=np.arange(.4, 4.101, .1))
    peak = int(np.argmax(counts))
    centre = float((edges[peak]+edges[peak+1])/2)
    in_layer = np.abs(values-centre) <= .18
    support = float(np.mean(in_layer))
    result['layer_support'] = round(support, 3)
    if support < .70:
        result['reason'] = 'ambiguous_pose_torso_layers'
        return result
    layer = values[in_layer]
    p10, median, p90 = np.percentile(layer, [10, 50, 90])
    if p90-p10 > max(.28, .15*median):
        result['reason'] = 'pose_torso_depth_spread_too_large'
        return result
    xs = np.nonzero(selected)[1]
    u = float(np.median(xs[in_layer])+x1)
    result.update(valid=True, reason='ok', distance_m=round(float(median), 4),
                  bearing_rad=float(math.atan2(u-cx, fx)),
                  depth_spread_m=round(float(p90-p10), 4))
    return result
