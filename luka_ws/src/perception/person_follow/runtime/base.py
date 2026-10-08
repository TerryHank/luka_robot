"""Stable backend contract for Luka person segmentation."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List

import numpy as np


class PersonSegmentationBackend(ABC):
    """Backend-neutral person segmentation interface."""

    backend_name = "unknown"
    fallback_reason = None

    @abstractmethod
    def detect(self, bgr: np.ndarray) -> List[Dict]:
        raise NotImplementedError

    @property
    def timings_ms(self) -> Dict[str, float]:
        return {}

    def close(self) -> None:
        return None


def validate_bgr(bgr: np.ndarray) -> tuple[int, int]:
    if not isinstance(bgr, np.ndarray) or bgr.dtype != np.uint8:
        raise ValueError("Expected uint8 BGR image")
    if bgr.ndim != 3 or bgr.shape[2] != 3:
        raise ValueError("Expected uint8 BGR image")
    height, width = bgr.shape[:2]
    if height <= 0 or width <= 0:
        raise ValueError("Expected non-empty BGR image")
    return height, width


def normalize_person_results(boxes, scores, classes, masks, image_shape, max_people=8):
    """Normalize YOLO segmentation output to Luka's existing list contract."""
    height, width = image_shape[:2]
    indices = sorted(
        (i for i, cls in enumerate(classes) if int(cls) == 0),
        key=lambda i: float(scores[i]),
        reverse=True,
    )
    detections = []
    for i in indices[:max_people]:
        x1, y1, x2, y2 = (int(value) for value in boxes[i])
        box = [max(0, x1), max(0, y1), min(width, x2), min(height, y2)]
        if box[2] <= box[0] or box[3] <= box[1]:
            continue
        mask = np.asarray(masks[i], dtype=np.uint8)
        expected = (box[3] - box[1], box[2] - box[0])
        if mask.shape != expected:
            raise ValueError(
                f"Person mask does not match its bounding box: {mask.shape} != {expected}"
            )
        detections.append(
            {
                "class": "person",
                "bbox": box,
                "confidence": round(float(scores[i]), 4),
                "person_mask": mask,
            }
        )
    return detections
