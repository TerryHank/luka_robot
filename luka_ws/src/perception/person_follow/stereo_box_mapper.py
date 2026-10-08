"""Map calibrated central stereo detections into the full left-eye image."""
import json
from pathlib import Path

import cv2
import numpy as np


class StereoBoxMapper:
    def __init__(self, calibration_path):
        cal = json.loads(Path(calibration_path).read_text(encoding='utf-8'))
        if cal.get('image_size') != [1280, 720] or not cal.get('validated_known_distances'):
            raise ValueError('stereo box mapper requires the validated 1280x720 calibration')
        self.map_x, self.map_y = cv2.convertMaps(*cv2.initUndistortRectifyMap(
            np.asarray(cal['left_k'], np.float64),
            np.asarray(cal['left_dist'], np.float64),
            np.asarray(cal['rect_l'], np.float64),
            np.asarray(cal['proj_l'], np.float64),
            (1280, 720), cv2.CV_16SC2), cv2.CV_32FC1)

    def to_full(self, rectified_box):
        try:
            x1, y1, x2, y2 = [float(v) for v in rectified_box]
        except (TypeError, ValueError, OverflowError):
            return None
        if (not np.isfinite([x1, y1, x2, y2]).all() or
                x2 <= x1 or y2 <= y1 or x2 <= 0 or x1 >= 640 or y2 <= 60 or y1 >= 420):
            return None
        xs = np.linspace(max(0., x1), min(639., x2), 9)
        ys = np.linspace(max(60., y1), min(419., y2), 9)
        px = np.clip(np.rint(xs*2).astype(int), 0, 1279)
        py = np.clip(np.rint((ys-60)*2).astype(int), 0, 719)
        raw_x = self.map_x[np.ix_(py, px)]/2
        raw_y = self.map_y[np.ix_(py, px)]/2+60
        valid = (raw_x >= 0) & (raw_x < 640) & (raw_y >= 60) & (raw_y < 420)
        if np.count_nonzero(valid) < 16:
            return None
        box = [float(raw_x[valid].min()), float(raw_y[valid].min()),
               float(raw_x[valid].max()), float(raw_y[valid].max())]
        return box if box[2]-box[0] >= 12 and box[3]-box[1] >= 24 else None


def combine_full_and_zoom(full_rows, zoom_rows, mapper, face_count=None):
    """Use both fields of view; consolidate only proven duplicate boxes."""
    rows = [dict(row) for row in full_rows]
    for source in zoom_rows:
        mapped = mapper.to_full(source.get('bbox'))
        if mapped is None:
            continue
        candidate = dict(source, bbox=mapped, detection_view='rectified_zoom')
        matched = None
        for index, row in enumerate(rows):
            a, b = np.asarray(row['bbox'], float), np.asarray(mapped, float)
            lo, hi = np.maximum(a[:2], b[:2]), np.minimum(a[2:], b[2:])
            intersection = float(np.prod(np.maximum(hi-lo, 0)))
            area_a, area_b = float(np.prod(a[2:]-a[:2])), float(np.prod(b[2:]-b[:2]))
            if intersection / max(min(area_a, area_b), 1) < .85:
                continue
            if face_count is None:
                continue
            union = [float(min(a[0], b[0])), float(min(a[1], b[1])),
                     float(max(a[2], b[2])), float(max(a[3], b[3]))]
            if face_count(union) == 1:
                matched = index
                break
        if matched is None:
            rows.append(candidate)
        else:
            original = rows[matched]
            a, b = np.asarray(original['bbox'], float), np.asarray(mapped, float)
            original['bbox'] = [float(min(a[0], b[0])), float(min(a[1], b[1])),
                                float(max(a[2], b[2])), float(max(a[3], b[3]))]
            original['confidence'] = max(float(original['confidence']), float(candidate['confidence']))
            original['detection_view'] = 'full_plus_rectified_zoom'
    return rows
