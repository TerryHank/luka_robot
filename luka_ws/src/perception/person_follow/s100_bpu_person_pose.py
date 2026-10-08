"""S100 official BPU person-pose model adapted for the shared RGB frame."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
import sys

import numpy as np


SAMPLE = Path('/app/pydev_demo/04_pose_sample/01_ultralytics_yolo11_pose/ultralytics_yolo11_pose.py')
MODEL = Path('/opt/hobot/model/s100/basic/yolo11n_pose_nashe_640x640_nv12.hbm')


class BpuPersonPose:
    def __init__(self, confidence=.35, max_people=8):
        if not SAMPLE.is_file() or not MODEL.is_file():
            raise FileNotFoundError('S100 person pose sample/model missing')
        sys.path.insert(0, '/app/pydev_demo')
        spec = spec_from_file_location('s100_official_yolo11_pose', SAMPLE)
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        self.model = module.YoloV11_Pose(SimpleNamespace(model_path=str(MODEL),
                                                          score_thres=confidence))
        self.model.set_scheduling_params(priority=0, bpu_cores=[0])
        self.max_people = int(max_people)

    def detect(self, bgr):
        if bgr.dtype != np.uint8 or bgr.ndim != 3 or bgr.shape[2] != 3:
            raise ValueError('Expected uint8 BGR image')
        height, width = bgr.shape[:2]
        outputs = self.model.forward(self.model.pre_process(bgr))
        classes, scores, boxes, points, logits = self.model.post_process(
            outputs, height, width)
        indices = [i for i, cls in enumerate(classes) if int(cls) == 0]
        indices.sort(key=lambda i: float(scores[i]), reverse=True)
        return [{'bbox': np.rint(boxes[i]).astype(int).tolist(),
                 'confidence': round(float(scores[i]), 4),
                 'points_xy': points[i], 'point_logits': logits[i]}
                for i in indices[:self.max_people]]

    def close(self):
        self.model = None
