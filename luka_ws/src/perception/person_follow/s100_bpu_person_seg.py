"""S100 BPU person-instance segmentation using the bundled official model.

Masks exist only in the current frame and must be removed before publishing
tracking data. The class intentionally does not control the robot.
"""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
import sys

import numpy as np


SAMPLE = Path('/app/pydev_demo/03_instance_segmentation_sample/02_ultralytics_yolo11_seg/ultralytics_yolo11_seg.py')
MODEL = Path('/opt/hobot/model/s100/basic/yolo11n_seg_nashe_640x640_nv12.hbm')


class BpuPersonSegmenter:
    def __init__(self, confidence=.35, max_people=8):
        if not SAMPLE.is_file() or not MODEL.is_file():
            raise FileNotFoundError('S100 person segmentation sample/model missing')
        sys.path.insert(0, '/app/pydev_demo')
        spec = spec_from_file_location('s100_official_yolo11_seg', SAMPLE)
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        options = SimpleNamespace(model_path=str(MODEL), score_thres=confidence,
                                  is_open=True)
        self.model = module.YoloV11_Seg(options)
        self.model.set_scheduling_params(priority=0, bpu_cores=[0])
        self.max_people = int(max_people)

    def detect(self, bgr):
        if bgr.dtype != np.uint8 or bgr.ndim != 3 or bgr.shape[2] != 3:
            raise ValueError('Expected uint8 BGR image')
        height, width = bgr.shape[:2]
        raw = self.model.forward(self.model.pre_process(bgr))
        boxes, classes, scores, masks = self.model.post_process(raw, width, height)
        indices = [i for i, cls in enumerate(classes) if int(cls) == 0]
        indices.sort(key=lambda i: float(scores[i]), reverse=True)
        detections = []
        for i in indices[:self.max_people]:
            x1, y1, x2, y2 = (int(v) for v in boxes[i])
            box = [max(0, x1), max(0, y1), min(width, x2), min(height, y2)]
            if box[2] <= box[0] or box[3] <= box[1]:
                continue
            mask = np.asarray(masks[i])
            if mask.shape != (box[3]-box[1], box[2]-box[0]):
                continue
            detections.append({'class': 'person', 'bbox': box,
                               'confidence': round(float(scores[i]), 4),
                               'person_mask': mask})
        return detections

    def close(self):
        self.model = None
