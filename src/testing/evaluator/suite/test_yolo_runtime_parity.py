"""Parity helpers for legacy vs D-Robotics YOLO26 runtime.

Pure geometry tests run anywhere. Board parity is opt-in and never publishes
ROS motion commands.
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[2] / "perception/person_follow"
sys.path.insert(0, str(ROOT))


def box_iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    area_a = max(0, a[2] - a[0]) * max(0, a[3] - a[1])
    area_b = max(0, b[2] - b[0]) * max(0, b[3] - b[1])
    union = area_a + area_b - inter
    return 0.0 if union <= 0 else inter / union


def mask_iou(a, b):
    a, b = np.asarray(a, dtype=bool), np.asarray(b, dtype=bool)
    if a.shape != b.shape:
        return 0.0
    union = np.logical_or(a, b).sum()
    return 1.0 if union == 0 else float(np.logical_and(a, b).sum() / union)


class GeometryParityTest(unittest.TestCase):
    def test_box_iou_identity(self):
        self.assertEqual(box_iou([1, 2, 10, 20], [1, 2, 10, 20]), 1.0)

    def test_mask_iou_identity(self):
        mask = np.array([[0, 1], [1, 1]], dtype=np.uint8)
        self.assertEqual(mask_iou(mask, mask), 1.0)


def board_parity(bgr):
    from runtime.factory import create_yolo26_person_segmenter

    legacy = create_yolo26_person_segmenter(backend="legacy")
    official = create_yolo26_person_segmenter(backend="drobotics")
    old, new = legacy.detect(bgr), official.detect(bgr)
    pairs = []
    for a, b in zip(old, new):
        pairs.append(
            {
                "bbox_iou": box_iou(a["bbox"], b["bbox"]),
                "score_delta": abs(a["confidence"] - b["confidence"]),
                "mask_iou": mask_iou(a["person_mask"], b["person_mask"]),
            }
        )
    return {
        "legacy_count": len(old),
        "drobotics_count": len(new),
        "pairs": pairs,
        "legacy_timings_ms": legacy.timings_ms,
        "drobotics_timings_ms": official.timings_ms,
    }


if __name__ == "__main__":
    unittest.main()
