"""S100 BPU person detector matching the existing person-follow detector API."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
import sys

import numpy as np

SAMPLE = Path("/app/pydev_demo/02_detection_sample/02_ultralytics_yolo11/ultralytics_yolo11.py")
MODEL = Path("/opt/hobot/model/s100/basic/yolo11n_detect_nashe_640x640_nv12.hbm")


class BpuPersonDetector:
    def __init__(self, confidence=0.35, max_people=8):
        if not SAMPLE.is_file() or not MODEL.is_file():
            raise FileNotFoundError("S100 YOLO11 BPU sample/model missing")
        sys.path.insert(0, "/app/pydev_demo")
        spec = spec_from_file_location("s100_official_yolo11", SAMPLE)
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        options = SimpleNamespace(model_path=str(MODEL), score_thres=confidence)
        self.model = module.YoloV11(options)
        self.model.set_scheduling_params(priority=0, bpu_cores=[0])
        self.max_people = int(max_people)

    def detect(self, bgr):
        if bgr.dtype != np.uint8 or bgr.ndim != 3 or bgr.shape[2] != 3:
            raise ValueError("Expected uint8 BGR image")
        height, width = bgr.shape[:2]
        raw = self.model.forward(self.model.pre_process(bgr))
        boxes, classes, scores = self.model.post_process(raw, width, height)
        indices = [i for i, cls in enumerate(classes) if int(cls) == 0]
        indices.sort(key=lambda i: float(scores[i]), reverse=True)
        return [{"class": "person",
                 "bbox": np.rint(boxes[i]).astype(int).tolist(),
                 "confidence": round(float(scores[i]), 4)}
                for i in indices[:self.max_people]]

    def close(self):
        self.model = None
