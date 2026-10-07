"""Unambiguous association between segmentation and pose detections."""


def box_overlap(a, b):
    left, top = max(a[0], b[0]), max(a[1], b[1])
    right, bottom = min(a[2], b[2]), min(a[3], b[3])
    area = max(0., right-left)*max(0., bottom-top)
    aa = max(0., a[2]-a[0])*max(0., a[3]-a[1])
    bb = max(0., b[2]-b[0])*max(0., b[3]-b[1])
    return area/max(1., aa+bb-area), area/max(1., aa), area/max(1., bb)


def box_iou(a, b):
    return box_overlap(a, b)[0]


def match_pose(seg_index, segments, poses, min_iou=.60, min_margin=.15):
    """Return (pose, reason); never guess when two associations are close."""
    if not 0 <= seg_index < len(segments):
        return None, 'invalid_segment_index'
    # When one person is alone, the pose model sometimes detects only the
    # visible upper body while the segmenter includes the full body. A low
    # IoU is then expected; accept only a substantial pose box contained in
    # that one segment. Never use this relaxed path in a crowd.
    if len(segments) == len(poses) == 1:
        iou, segment_covered, pose_covered = box_overlap(
            segments[0]['bbox'], poses[0]['bbox'])
        if iou < min_iou and segment_covered >= .35 and pose_covered >= .85:
            return poses[0], 'ok_partial_pose'
    scores = sorted(((box_iou(segments[seg_index]['bbox'], row['bbox']), i)
                     for i, row in enumerate(poses)), reverse=True)
    if not scores or scores[0][0] < min_iou:
        return None, 'pose_not_matched'
    if len(scores) > 1 and scores[0][0]-scores[1][0] < min_margin:
        return None, 'pose_association_ambiguous'
    best_iou, best_index = scores[0]
    for i, segment in enumerate(segments):
        if i != seg_index and box_iou(segment['bbox'], poses[best_index]['bbox']) >= best_iou-min_margin:
            return None, 'pose_association_ambiguous'
    return poses[best_index], 'ok'
