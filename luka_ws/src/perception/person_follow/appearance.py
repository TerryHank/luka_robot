"""Small CPU body descriptor. Features stay in RAM and are not face identity."""
from pathlib import Path
import time
import numpy as np


class BodyAppearance:
    DIMENSION = 512

    def __init__(self, model_path):
        import cv2
        self.cv2 = cv2
        self.net = cv2.dnn.readNetFromONNX(str(Path(model_path)))
        self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
        self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
        self.last_duration_s = 0.
        self.mean = np.array([.485, .456, .406], dtype=np.float32)
        self.std = np.array([.229, .224, .225], dtype=np.float32)

    def embed(self, bgr, bbox):
        started = time.monotonic()
        if (not isinstance(bgr, np.ndarray) or bgr.ndim != 3 or
                bgr.shape[2] != 3 or bgr.dtype != np.uint8):
            return None
        try:
            box = np.asarray(bbox, dtype=float)
        except (ValueError, TypeError):
            return None
        if box.shape != (4,) or not np.isfinite(box).all():
            return None
        h, w = bgr.shape[:2]
        x1, y1 = np.maximum(np.floor(box[:2]), 0).astype(int)
        x2, y2 = np.minimum(np.ceil(box[2:]), [w, h]).astype(int)
        if x2-x1 < 32 or y2-y1 < 64:
            return None
        rgb = self.cv2.cvtColor(bgr[y1:y2, x1:x2], self.cv2.COLOR_BGR2RGB)
        resized = self.cv2.resize(rgb, (128, 256), interpolation=self.cv2.INTER_LINEAR)
        normalized = (resized.astype(np.float32)/255. - self.mean) / self.std
        blob = np.ascontiguousarray(normalized.transpose(2, 0, 1)[None])
        self.net.setInput(blob)
        vector = np.asarray(self.net.forward(), dtype=np.float32).reshape(-1)
        self.last_duration_s = time.monotonic()-started
        if vector.size != self.DIMENSION or not np.isfinite(vector).all():
            return None
        norm = float(np.linalg.norm(vector))
        if norm < 1e-8:
            return None
        return vector / norm
