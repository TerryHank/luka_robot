"""S100 BPU YOLO26 segmentation with person-only application output."""
import os
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT/'bpu_yolo26_runtime'))
from yolo26_seg import YOLO26Seg, YOLO26SegConfig

MODEL = os.getenv('NX_YOLO26_MODEL', '/home/sunrise/yolo26m-objv1-seg.pt')
HBM = Path('/home/sunrise/luka_data/ml_models/person_follow/bpu_yolo26/yolo26m_objv1_seg_bpu_nashe_640x640_nv12.hbm')


class Yolo26PersonSegmenter:
    def __init__(self, confidence=.35, max_people=8):
        self.model = YOLO26Seg(YOLO26SegConfig(model_path=str(HBM),
            classes_num=365, score_thres=confidence, resize_type=1, class_id=0))
        self.model.set_scheduling_params(priority=0, bpu_cores=[0])
        self.max_people = max_people

    def detect(self, bgr):
        if bgr.dtype != np.uint8 or bgr.ndim != 3 or bgr.shape[2] != 3:
            raise ValueError('Expected uint8 BGR image')
        height, width = bgr.shape[:2]
        boxes, scores, classes, masks = self.model.predict(bgr)
        indices = sorted((i for i, cls in enumerate(classes) if int(cls)==0),
            key=lambda i: float(scores[i]), reverse=True)
        detections = []
        for i in indices[:self.max_people]:
            x1, y1, x2, y2 = (int(value) for value in boxes[i])
            box = [max(0,x1), max(0,y1), min(width,x2), min(height,y2)]
            if box[2] <= box[0] or box[3] <= box[1]:
                continue
            mask = np.asarray(masks[i], dtype=np.uint8)
            if mask.shape != (box[3]-box[1], box[2]-box[0]):
                raise ValueError('Person mask does not match its bounding box')
            detections.append({'class': 'person', 'bbox': box,
                'confidence': round(float(scores[i]), 4), 'person_mask': mask})
        return detections

    def close(self):
        self.model = None
