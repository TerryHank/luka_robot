"""Person segmentation runtime selection with explicit rollback."""
from __future__ import annotations

import os


def create_yolo26_person_segmenter(confidence=.35, max_people=8, backend=None):
    backend = (
        backend or os.getenv("NX_YOLO26_RUNTIME_BACKEND", "legacy")
    ).strip().lower()
    if backend == "legacy":
        from .luka_legacy import LukaLegacyYolo26Backend
        return LukaLegacyYolo26Backend(
            confidence=confidence, max_people=max_people
        )
    if backend == "drobotics":
        try:
            from .drobotics_yolo26 import DRoboticsYolo26Backend
            return DRoboticsYolo26Backend(
                confidence=confidence, max_people=max_people
            )
        except Exception as exc:
            if os.getenv("NX_YOLO26_RUNTIME_ALLOW_FALLBACK", "0") != "1":
                raise
            from .luka_legacy import LukaLegacyYolo26Backend
            fallback = LukaLegacyYolo26Backend(
                confidence=confidence, max_people=max_people
            )
            fallback.fallback_reason = (
                "drobotics runtime unavailable; legacy fallback: "
                + type(exc).__name__
            )
            return fallback
    raise ValueError(
        "NX_YOLO26_RUNTIME_BACKEND must be 'legacy' or 'drobotics'"
    )
