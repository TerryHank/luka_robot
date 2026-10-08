"""YuNet/SFace face primitives only; no person detector, tracker or navigation."""
import math
from pathlib import Path
import threading
import numpy as np

def _box(box, width, height):
    values = np.asarray(box, dtype=float)
    if values.shape != (4,) or not np.isfinite(values).all():
        raise ValueError("bbox must contain four finite xyxy values")
    x1, y1, x2, y2 = values
    x1, x2 = np.clip([x1, x2], 0, width)
    y1, y2 = np.clip([y1, y2], 0, height)
    if x2 <= x1 or y2 <= y1:
        raise ValueError("bbox has no area")
    return tuple(map(float, (x1, y1, x2, y2)))

def face_pose_quality(face, crop_shape, min_face_px=64):
    """Reject incomplete or weak detections without imposing a frontal pose."""
    row = np.asarray(face, dtype=float)
    if row.size < 15 or not np.isfinite(row).all():
        return 0., "invalid_face"
    x, y, width, height = row[:4]
    ch, cw = crop_shape[:2]
    if min(width, height) < min_face_px:
        return 0., "face_too_small"
    if x < 2 or y < 2 or x + width > cw - 2 or y + height > ch - 2:
        return 0., "face_clipped"
    if row[14] < .65:
        return 0., "face_low_confidence"
    return float(np.clip(row[14], 0, 1)), "ok"

class FaceFeatures:
    def __init__(self, yunet_path, sface_path, min_face_px=64, distant_min_face_px=40,
                 blur_threshold=45.):
        import cv2
        if not Path(yunet_path).is_file() or not Path(sface_path).is_file():
            raise FileNotFoundError("YuNet and SFace ONNX files are required")
        self.cv2, self.lock = cv2, threading.Lock()
        self.detector = cv2.FaceDetectorYN_create(str(yunet_path), "", (320, 320), .65, .3, 200,
                                                  cv2.dnn.DNN_BACKEND_OPENCV, cv2.dnn.DNN_TARGET_CPU)
        self.recognizer = cv2.FaceRecognizerSF_create(str(sface_path), "",
                                                      cv2.dnn.DNN_BACKEND_OPENCV, cv2.dnn.DNN_TARGET_CPU)
        if not 32 <= distant_min_face_px < min_face_px:
            raise ValueError("Distant face threshold must be 32px through the enrollment threshold")
        self.min_face_px, self.distant_min_face_px = min_face_px, distant_min_face_px
        self.blur_threshold = blur_threshold

    def count_faces(self, bgr, bbox):
        """Count detected faces to reject nested multi-person boxes, not identify."""
        h, w = bgr.shape[:2]
        x1, y1, x2, y2 = _box(bbox, w, h)
        crop = np.ascontiguousarray(bgr[int(y1):int(math.ceil(y2)), int(x1):int(math.ceil(x2))])
        if min(crop.shape[:2]) < 20:
            return 0
        with self.lock:
            self.detector.setInputSize((crop.shape[1], crop.shape[0]))
            _, found = self.detector.detect(crop)
        return 0 if found is None else len(found)

    def face_features(self, bgr, body_bbox):
        """Return identity features for one clear face inside a person, including side views."""
        result = {"accepted": False, "face_bbox": None, "embedding": None,
                  "quality": 0., "reason": "no_face", "upscaled": False,
                  "source_face_px": None, "enrollment_eligible": False}
        h, w = bgr.shape[:2]
        x1, y1, x2, y2 = _box(body_bbox, w, h)
        # A side-turned head can extend beyond the body detector's rectangle.
        # Expand only the head region; multiple faces inside it remain ambiguous.
        body_width, body_height = x2 - x1, y2 - y1
        left = max(0, int(x1 - .15 * body_width))
        right = min(w, int(math.ceil(x2 + .15 * body_width)))
        top = max(0, int(y1 - .08 * body_height))
        bottom = min(h, int(math.ceil(y1 + .68 * body_height)))
        crop = np.ascontiguousarray(bgr[top:bottom, left:right])
        if min(crop.shape[:2]) < self.min_face_px:
            result["reason"] = "body_crop_too_small"
            return result
        with self.lock:
            self.detector.setInputSize((crop.shape[1], crop.shape[0]))
            _, faces = self.detector.detect(crop)
            if faces is None or not len(faces):
                return result
            if len(faces) != 1:
                result["reason"] = "multiple_faces_in_body"
                return result
            face = faces[0]
            fx, fy, fw, fh = map(float, face[:4])
            face_cx = left + fx + fw / 2
            if not x1 - .10 * body_width <= face_cx <= x2 + .10 * body_width:
                result["reason"] = "face_outside_body"
                return result
            result["face_bbox"] = [int(round(left + fx)), int(round(top + fy)),
                                   int(round(left + fx + fw)), int(round(top + fy + fh))]
            source_face_px = min(fw, fh)
            result["source_face_px"] = round(source_face_px, 1)
            result["enrollment_eligible"] = source_face_px >= self.min_face_px
            model_crop, model_face = crop, face
            # Enlarging does not invent facial detail.  It only lets SFace use
            # a detected, reasonably sampled 40–63px face at its supported
            # input scale.  Such a feature is deliberately never enrolled and
            # the caller requires stricter repeated confirmation.
            if self.distant_min_face_px <= source_face_px < self.min_face_px:
                scale = min(2., 128. / source_face_px)
                model_crop = self.cv2.resize(crop, None, fx=scale, fy=scale,
                                              interpolation=self.cv2.INTER_CUBIC)
                model_face = np.asarray(face, dtype=np.float32).copy()
                model_face[:14] *= scale
                result["upscaled"] = True
            quality, reason = face_pose_quality(model_face, model_crop.shape, self.min_face_px)
            result.update(quality=quality, reason=reason)
            if reason != "ok":
                return result
            aligned = self.recognizer.alignCrop(model_crop, model_face)
            blur = float(self.cv2.Laplacian(self.cv2.cvtColor(aligned, self.cv2.COLOR_BGR2GRAY),
                                            self.cv2.CV_64F).var())
            result["sharpness"] = round(blur, 2)
            if blur < self.blur_threshold:
                result.update(quality=0., reason="face_blurry")
                return result
            embedding = np.asarray(self.recognizer.feature(aligned), dtype=np.float32).reshape(-1)
        norm = float(np.linalg.norm(embedding))
        if not np.isfinite(embedding).all() or norm < 1e-8 or embedding.size != 128:
            result.update(quality=0., reason="invalid_embedding")
            return result
        result.update(accepted=True, embedding=embedding / norm, reason="ok")
        return result
