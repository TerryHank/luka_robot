"""Adapter for Luka's accepted optimized YOLO26 S100 runtime."""
from __future__ import annotations

from .base import PersonSegmentationBackend, validate_bgr
from yolo26_bpu_person import Yolo26PersonSegmenter as LegacySegmenter


class LukaLegacyYolo26Backend(PersonSegmentationBackend):
    backend_name = "legacy"

    def __init__(self, confidence=.35, max_people=8):
        self.impl = LegacySegmenter(confidence=confidence, max_people=max_people)
        self.model = self.impl.model

    def detect(self, bgr):
        validate_bgr(bgr)
        return self.impl.detect(bgr)

    @property
    def timings_ms(self):
        return dict(getattr(self.model, "last_timings_ms", {}) or {})

    def close(self):
        self.impl.close()
