"""Adapter for the pinned D-Robotics rdk_model_zoo_s YOLO26 runtime."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
import time

from .base import PersonSegmentationBackend, normalize_person_results, validate_bgr


class DRoboticsYolo26Backend(PersonSegmentationBackend):
    """Load the official Model Zoo wrapper without copying it into Luka."""

    backend_name = "drobotics"

    def __init__(self, confidence=.35, max_people=8, model_path=None, model_zoo_root=None):
        self.max_people = int(max_people)
        self._timings_ms = {}
        root = Path(
            model_zoo_root
            or os.getenv("RDK_MODEL_ZOO_S_ROOT", "/opt/rdk_model_zoo_s")
        ).resolve()
        runtime_dir = root / "samples/Vision/ultralytics_yolo26/runtime/python"
        module_path = runtime_dir / "yolo26_seg.py"
        if not module_path.is_file():
            raise FileNotFoundError(
                f"D-Robotics YOLO26 runtime not found: {module_path}; "
                "set RDK_MODEL_ZOO_S_ROOT to the pinned rdk_model_zoo_s checkout"
            )

        for path in (str(root), str(runtime_dir)):
            if path not in sys.path:
                sys.path.insert(0, path)

        module_name = "_luka_drobotics_yolo26_seg"
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load D-Robotics runtime: {module_path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        default_hbm = (
            Path(__file__).resolve().parents[1]
            / "models/bpu_yolo26/yolo26m_objv1_seg_bpu_nashe_640x640_nv12.hbm"
        )
        model_path = Path(
            model_path or os.getenv("NX_YOLO26_HBM", str(default_hbm))
        ).resolve()
        if not model_path.is_file():
            raise FileNotFoundError(f"YOLO26 HBM not found: {model_path}")

        classes_num = int(os.getenv("NX_YOLO26_CLASSES_NUM", "365"))
        config = module.YOLO26SegConfig(
            model_path=str(model_path),
            classes_num=classes_num,
            score_thres=float(confidence),
            resize_type=1,
        )
        self.model = module.YOLO26Seg(config)
        self.model.set_scheduling_params(priority=0, bpu_cores=[0])

    def detect(self, bgr):
        validate_bgr(bgr)
        height, width = bgr.shape[:2]
        started = time.perf_counter()
        tensor = self.model.pre_process(bgr)
        after_pre = time.perf_counter()
        outputs = self.model.forward(tensor)
        after_forward = time.perf_counter()
        boxes, scores, classes, masks = self.model.post_process(
            outputs, width, height
        )
        after_post = time.perf_counter()
        self._timings_ms = {
            "preprocess": (after_pre - started) * 1000.0,
            "forward": (after_forward - after_pre) * 1000.0,
            "postprocess": (after_post - after_forward) * 1000.0,
            "total": (after_post - started) * 1000.0,
        }
        return normalize_person_results(
            boxes, scores, classes, masks, bgr.shape, self.max_people
        )

    @property
    def timings_ms(self):
        return dict(self._timings_ms)

    def close(self):
        self.model = None
