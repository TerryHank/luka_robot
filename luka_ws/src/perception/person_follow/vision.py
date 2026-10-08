"""Bounded vision primitives for the static person monitor (no ROS or motion).

CUDA and face models load only when their classes are explicitly constructed.
Depth must be registered to RGB and supplied in metres. Geometry is an estimate
from the torso ROI, not proof that space around a person is traversable.
"""
from __future__ import annotations

import ctypes as C
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


def _nms(boxes, scores, threshold=.45):
    order = np.argsort(-scores, kind="stable")
    keep = []
    while order.size:
        index = int(order[0])
        keep.append(index)
        rest = order[1:]
        if not rest.size:
            break
        a, b = boxes[index], boxes[rest]
        lt, rb = np.maximum(a[:2], b[:, :2]), np.minimum(a[2:], b[:, 2:])
        area = np.prod(np.maximum(0., rb - lt), axis=1)
        union = np.prod(a[2:] - a[:2]) + np.prod(b[:, 2:] - b[:, :2], axis=1) - area
        order = rest[area / np.maximum(union, 1e-9) <= threshold]
    return keep


def decode_coco_people(raw, frame_shape, input_hw=(640, 640), confidence=.45,
                       max_people=8, iou_threshold=.45):
    """Decode YOLO11 raw 80-class output; reject incompatible engine layouts."""
    values = np.asarray(raw)
    if values.ndim != 3 or values.shape[0] != 1:
        raise ValueError("Expected one YOLO COCO batch")
    rows = values[0].T if values.shape[1] == 84 else values[0]
    if rows.ndim != 2 or rows.shape[1] != 84:
        raise ValueError("Expected raw 84-channel COCO output, not household/NMS output")
    rows = rows[np.isfinite(rows).all(axis=1)]
    if not len(rows):
        return []
    scores = rows[:, 4:]
    select = ((scores.argmax(axis=1) == 0) & (scores[:, 0] >= confidence)
              & (scores[:, 0] <= 1.) & (rows[:, 2] > 0) & (rows[:, 3] > 0))
    rows = rows[select]
    if not len(rows):
        return []
    height, width = frame_shape[:2]
    ih, iw = input_hw
    ratio = min(iw / width, ih / height)
    padx, pady = (iw - round(width * ratio)) // 2, (ih - round(height * ratio)) // 2
    xyxy = np.concatenate((rows[:, :2] - rows[:, 2:4] / 2,
                           rows[:, :2] + rows[:, 2:4] / 2), axis=1)
    xyxy = (xyxy - [padx, pady, padx, pady]) / ratio
    xyxy[:, [0, 2]] = np.clip(xyxy[:, [0, 2]], 0, width)
    xyxy[:, [1, 3]] = np.clip(xyxy[:, [1, 3]], 0, height)
    valid = np.all(xyxy[:, 2:] - xyxy[:, :2] >= 6, axis=1)
    xyxy, rows = xyxy[valid], rows[valid]
    indices = _nms(xyxy, rows[:, 4], iou_threshold)[:max_people]
    return [{"class": "person", "bbox": np.rint(xyxy[i]).astype(int).tolist(),
             "confidence": round(float(rows[i, 4]), 4)} for i in indices]


def decode_peoplenet_people(cov, bbox, frame_shape, input_hw=(544, 960),
                            confidence=.40, max_people=8, iou_threshold=.50):
    """Decode NVIDIA DetectNet_v2 PeopleNet person coverage and box tensors.

    The deployable ONNX has three classes (person, bag, face).  This monitor
    deliberately consumes only class zero.  PeopleNet is resized directly,
    matching NVIDIA's supplied ``maintain-aspect-ratio=0`` configuration.
    """
    if not .05 <= confidence <= 1 or not 1 <= max_people <= 32:
        raise ValueError("Invalid PeopleNet detector limits")
    ih, iw = input_hw
    cov = np.asarray(cov, dtype=np.float32)
    bbox = np.asarray(bbox, dtype=np.float32)
    if cov.shape != (1, 3, ih // 16, iw // 16):
        raise ValueError("Unexpected PeopleNet coverage tensor shape")
    if bbox.shape != (1, 12, ih // 16, iw // 16):
        raise ValueError("Unexpected PeopleNet bbox tensor shape")
    coverage, offsets = cov[0, 0], bbox[0, :4]
    ys, xs = np.where(np.isfinite(coverage) & (coverage >= confidence) & (coverage <= 1.0))
    if not len(xs):
        return []
    scores = coverage[ys, xs]
    # This is the public DetectNet_v2 grid/box transform used by NVIDIA's
    # DeepStream parser.  bboxNorm=35 and stride=16 are fixed by PeopleNet.
    cx, cy = (xs * 16 + .5) / 35., (ys * 16 + .5) / 35.
    xyxy = np.column_stack(((offsets[0, ys, xs] - cx) * -35.,
                            (offsets[1, ys, xs] - cy) * -35.,
                            (offsets[2, ys, xs] + cx) * 35.,
                            (offsets[3, ys, xs] + cy) * 35.))
    finite = np.isfinite(xyxy).all(axis=1)
    xyxy, scores = xyxy[finite], scores[finite]
    if not len(xyxy):
        return []
    xyxy[:, [0, 2]] = np.clip(xyxy[:, [0, 2]], 0, iw - 1)
    xyxy[:, [1, 3]] = np.clip(xyxy[:, [1, 3]], 0, ih - 1)
    valid = np.all(xyxy[:, 2:] - xyxy[:, :2] >= 6, axis=1)
    xyxy, scores = xyxy[valid], scores[valid]
    if not len(xyxy):
        return []
    height, width = frame_shape[:2]
    xyxy[:, [0, 2]] *= width / iw
    xyxy[:, [1, 3]] *= height / ih
    indices = _nms(xyxy, scores, iou_threshold)[:max_people]
    return [{"class": "person", "bbox": np.rint(xyxy[i]).astype(int).tolist(),
             "confidence": round(float(scores[i]), 4)} for i in indices]


class TrtRunner:
    """Single static TensorRT 10 engine, with deterministic CUDA buffer cleanup."""
    def __init__(self, path):
        import tensorrt as trt
        self.lock = threading.Lock()
        self.buffers = {}
        self.stream = C.c_void_p()
        self.cuda = None
        self.engine = self.context = self.runtime = None
        self.closed = False
        try:
            self.logger = trt.Logger(trt.Logger.WARNING)
            self.runtime = trt.Runtime(self.logger)
            self.engine = self.runtime.deserialize_cuda_engine(Path(path).read_bytes())
            if self.engine is None:
                raise RuntimeError("Person TensorRT engine cannot be deserialized")
            self.context = self.engine.create_execution_context()
            if self.context is None:
                raise RuntimeError("Person TensorRT context creation failed")
            self.cuda = C.CDLL("/usr/local/cuda/lib64/libcudart.so.12")
            signatures = {
                "cudaMalloc": [C.POINTER(C.c_void_p), C.c_size_t],
                "cudaMemcpy": [C.c_void_p, C.c_void_p, C.c_size_t, C.c_int],
                "cudaStreamCreate": [C.POINTER(C.c_void_p)],
                "cudaStreamSynchronize": [C.c_void_p],
                "cudaFree": [C.c_void_p], "cudaStreamDestroy": [C.c_void_p],
            }
            for name, arguments in signatures.items():
                function = getattr(self.cuda, name)
                function.argtypes, function.restype = arguments, C.c_int
            self._check(self.cuda.cudaStreamCreate(C.byref(self.stream)))
            inputs, outputs = [], []
            for i in range(self.engine.num_io_tensors):
                name = self.engine.get_tensor_name(i)
                shape = tuple(self.engine.get_tensor_shape(name))
                if not shape or min(shape) <= 0:
                    raise ValueError("Person detector requires a static engine")
                host = np.empty(shape, dtype=trt.nptype(self.engine.get_tensor_dtype(name)))
                ptr = C.c_void_p()
                self._check(self.cuda.cudaMalloc(C.byref(ptr), host.nbytes))
                self.buffers[name] = (host, ptr)
                if not self.context.set_tensor_address(name, ptr.value):
                    raise RuntimeError("Cannot bind person detector tensor")
                (inputs if self.engine.get_tensor_mode(name) == trt.TensorIOMode.INPUT
                 else outputs).append(name)
            if len(inputs) != 1 or len(outputs) != 1:
                raise ValueError("Person detector requires one input and one raw output")
            self.input, self.output = inputs[0], outputs[0]
            self.input_shape = self.buffers[self.input][0].shape
            if len(self.input_shape) != 4 or self.input_shape[:2] != (1, 3):
                raise ValueError("Person detector requires NCHW RGB input")
        except Exception:
            self.close()
            raise

    @staticmethod
    def _check(code):
        if code:
            raise RuntimeError("CUDA operation failed: %s" % code)

    def __call__(self, blob):
        with self.lock:
            if self.closed:
                raise RuntimeError("Person engine is closed")
            host, device = self.buffers[self.input]
            if blob.shape != host.shape:
                raise ValueError("Unexpected person detector input shape")
            np.copyto(host, blob, casting="same_kind")
            self._check(self.cuda.cudaMemcpy(device, C.c_void_p(host.ctypes.data), host.nbytes, 1))
            if not self.context.execute_async_v3(self.stream.value):
                raise RuntimeError("Person TensorRT execution failed")
            self._check(self.cuda.cudaStreamSynchronize(self.stream))
            host, device = self.buffers[self.output]
            self._check(self.cuda.cudaMemcpy(C.c_void_p(host.ctypes.data), device, host.nbytes, 2))
            return host.copy()

    def close(self):
        with self.lock:
            if self.closed:
                return
            if self.cuda is not None:
                if self.stream.value:
                    self.cuda.cudaStreamSynchronize(self.stream)
                self.context = None
                for _, ptr in self.buffers.values():
                    self.cuda.cudaFree(ptr)
                if self.stream.value:
                    self.cuda.cudaStreamDestroy(self.stream)
            self.buffers.clear()
            self.stream = C.c_void_p()
            self.engine = self.runtime = None
            self.closed = True

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


class PersonDetector:
    def __init__(self, engine_path, confidence=.45, max_people=8):
        if not .05 <= confidence <= 1 or not 1 <= max_people <= 32:
            raise ValueError("Invalid person detector limits")
        self.confidence, self.max_people = confidence, max_people
        self.runner = TrtRunner(engine_path)
        self.input_hw = self.runner.input_shape[2:]

    def detect(self, bgr):
        import cv2
        if bgr.ndim != 3 or bgr.shape[2] != 3 or bgr.dtype != np.uint8:
            raise ValueError("Person detector requires a uint8 BGR image")
        height, width = bgr.shape[:2]
        ih, iw = self.input_hw
        ratio = min(iw / width, ih / height)
        nw, nh = round(width * ratio), round(height * ratio)
        px, py = (iw - nw) // 2, (ih - nh) // 2
        canvas = np.full((ih, iw, 3), 114, dtype=np.uint8)
        canvas[py:py + nh, px:px + nw] = cv2.resize(bgr, (nw, nh))
        blob = np.ascontiguousarray(canvas[:, :, ::-1].transpose(2, 0, 1)[None], dtype=np.float32) / 255.
        raw = self.runner(blob)
        return decode_coco_people(raw, bgr.shape, self.input_hw, self.confidence, self.max_people)

    def close(self):
        self.runner.close()


class TrtMultiRunner:
    """Static TensorRT runner for an engine with one input and several outputs."""
    def __init__(self, path, expected_outputs=2):
        import tensorrt as trt
        self.lock, self.buffers = threading.Lock(), {}
        self.stream = C.c_void_p()
        self.cuda = self.engine = self.context = self.runtime = None
        self.closed = False
        try:
            self.logger = trt.Logger(trt.Logger.WARNING)
            self.runtime = trt.Runtime(self.logger)
            self.engine = self.runtime.deserialize_cuda_engine(Path(path).read_bytes())
            if self.engine is None:
                raise RuntimeError("PeopleNet TensorRT engine cannot be deserialized")
            self.context = self.engine.create_execution_context()
            if self.context is None:
                raise RuntimeError("PeopleNet TensorRT context creation failed")
            self.cuda = C.CDLL("/usr/local/cuda/lib64/libcudart.so.12")
            for name, arguments in {
                "cudaMalloc": [C.POINTER(C.c_void_p), C.c_size_t],
                "cudaMemcpy": [C.c_void_p, C.c_void_p, C.c_size_t, C.c_int],
                "cudaStreamCreate": [C.POINTER(C.c_void_p)],
                "cudaStreamSynchronize": [C.c_void_p],
                "cudaFree": [C.c_void_p], "cudaStreamDestroy": [C.c_void_p],
            }.items():
                function = getattr(self.cuda, name)
                function.argtypes, function.restype = arguments, C.c_int
            self._check(self.cuda.cudaStreamCreate(C.byref(self.stream)))
            inputs, outputs = [], []
            for i in range(self.engine.num_io_tensors):
                name = self.engine.get_tensor_name(i)
                shape = tuple(self.engine.get_tensor_shape(name))
                if not shape or min(shape) <= 0:
                    raise ValueError("PeopleNet requires a static engine")
                host = np.empty(shape, dtype=trt.nptype(self.engine.get_tensor_dtype(name)))
                ptr = C.c_void_p(); self._check(self.cuda.cudaMalloc(C.byref(ptr), host.nbytes))
                self.buffers[name] = (host, ptr)
                if not self.context.set_tensor_address(name, ptr.value):
                    raise RuntimeError("Cannot bind PeopleNet tensor")
                (inputs if self.engine.get_tensor_mode(name) == trt.TensorIOMode.INPUT else outputs).append(name)
            if len(inputs) != 1 or len(outputs) != expected_outputs:
                raise ValueError("Unexpected PeopleNet tensor count")
            self.input, self.outputs = inputs[0], tuple(outputs)
            self.input_shape = self.buffers[self.input][0].shape
        except Exception:
            self.close()
            raise

    @staticmethod
    def _check(code):
        if code:
            raise RuntimeError("CUDA operation failed: %s" % code)

    def __call__(self, blob):
        with self.lock:
            if self.closed:
                raise RuntimeError("PeopleNet engine is closed")
            host, device = self.buffers[self.input]
            if blob.shape != host.shape:
                raise ValueError("Unexpected PeopleNet input shape")
            np.copyto(host, blob, casting="same_kind")
            self._check(self.cuda.cudaMemcpy(device, C.c_void_p(host.ctypes.data), host.nbytes, 1))
            if not self.context.execute_async_v3(self.stream.value):
                raise RuntimeError("PeopleNet TensorRT execution failed")
            self._check(self.cuda.cudaStreamSynchronize(self.stream))
            result = {}
            for name in self.outputs:
                host, device = self.buffers[name]
                self._check(self.cuda.cudaMemcpy(C.c_void_p(host.ctypes.data), device, host.nbytes, 2))
                result[name] = host.copy()
            return result

    def close(self):
        with self.lock:
            if self.closed:
                return
            if self.cuda is not None:
                if self.stream.value:
                    self.cuda.cudaStreamSynchronize(self.stream)
                self.context = None
                for _, ptr in self.buffers.values():
                    self.cuda.cudaFree(ptr)
                if self.stream.value:
                    self.cuda.cudaStreamDestroy(self.stream)
            self.buffers.clear(); self.stream = C.c_void_p()
            self.engine = self.runtime = None; self.closed = True

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


class PeopleNetDetector:
    """NVIDIA PeopleNet detector, intentionally restricted to the person class."""
    INPUT_HW = (544, 960)

    def __init__(self, engine_path, confidence=.40, max_people=8):
        self.confidence, self.max_people = confidence, max_people
        self.runner = TrtMultiRunner(engine_path)
        if self.runner.input_shape != (1, 3, *self.INPUT_HW):
            self.close()
            raise ValueError("Unexpected PeopleNet input tensor shape")
        shapes = {name: self.runner.buffers[name][0].shape for name in self.runner.outputs}
        self.cov_name = next((name for name, shape in shapes.items() if shape == (1, 3, 34, 60)), None)
        self.bbox_name = next((name for name, shape in shapes.items() if shape == (1, 12, 34, 60)), None)
        if not self.cov_name or not self.bbox_name:
            self.close()
            raise ValueError("Unexpected PeopleNet output tensor shapes")

    def detect(self, bgr):
        import cv2
        if bgr.ndim != 3 or bgr.shape[2] != 3 or bgr.dtype != np.uint8:
            raise ValueError("PeopleNet requires a uint8 BGR image")
        ih, iw = self.INPUT_HW
        resized = cv2.resize(bgr, (iw, ih), interpolation=cv2.INTER_LINEAR)
        blob = np.ascontiguousarray(resized[:, :, ::-1].transpose(2, 0, 1)[None], dtype=np.float32) / 255.
        outputs = self.runner(blob)
        return decode_peoplenet_people(outputs[self.cov_name], outputs[self.bbox_name], bgr.shape,
                                       self.INPUT_HW, self.confidence, self.max_people)

    def close(self):
        self.runner.close()


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


def estimate_person_geometry(depth_m, bbox, intrinsics, skew_s=0., max_skew_s=.12,
                             min_depth_m=.20, max_depth_m=6.):
    """Return torso distance and horizontal bearing, or an explicit unknown reason.

    Reject an upper-body crop cut by the image top: a floor-level camera often
    only sees legs, and the middle of that box is not a trustworthy torso ROI.
    The caller must enforce registration and frame freshness before use.
    """
    result = {"valid": False, "distance_m": None, "bearing_rad": None,
              "reason": "invalid_depth", "source": "torso_depth_estimate"}
    depth = np.asarray(depth_m)
    if depth.ndim != 2 or not np.issubdtype(depth.dtype, np.floating):
        result["reason"] = "depth_must_be_float_metres"
        return result
    if not math.isfinite(skew_s) or abs(skew_s) > max_skew_s:
        result["reason"] = "rgb_depth_not_synchronized"
        return result
    try:
        fx = float(intrinsics.get("fx", intrinsics.get("fX")))
        cx = float(intrinsics.get("cx", intrinsics.get("cX")))
        if not math.isfinite(fx) or fx <= 0 or not math.isfinite(cx):
            raise ValueError()
        h, w = depth.shape
        x1, y1, x2, y2 = _box(bbox, w, h)
    except (ValueError, TypeError, KeyError, AttributeError):
        result["reason"] = "invalid_geometry_inputs"
        return result
    if y1 <= 2:
        result["reason"] = "person_upper_body_clipped"
        return result
    bw, bh = x2 - x1, y2 - y1
    left, right = int(x1 + .32 * bw), int(math.ceil(x1 + .68 * bw))
    top, bottom = int(y1 + .24 * bh), int(math.ceil(y1 + .55 * bh))
    result["depth_roi"] = [left, top, right, bottom]
    patch = depth[top:bottom, left:right]
    mask = np.isfinite(patch) & (patch >= min_depth_m) & (patch <= max_depth_m)
    count = int(mask.sum())
    fraction = count / max(patch.size, 1)
    result.update(valid_pixels=count, valid_fraction=round(fraction, 3))
    if count < 32 or fraction < .45:
        result["reason"] = "insufficient_torso_depth"
        return result
    values = np.sort(patch[mask])
    clusters = np.split(values, np.flatnonzero(np.diff(values) > .12) + 1)
    substantial = [cluster for cluster in clusters if len(cluster) >= max(16, .15 * count)]
    if not substantial:
        result["reason"] = "incoherent_torso_depth"
        return result
    foreground = substantial[0]
    support = len(foreground) / count
    result["foreground_fraction"] = round(support, 3)
    if support < .65:
        result["reason"] = "ambiguous_depth_layers"
        return result
    p10, p25, median, p75, p90 = np.percentile(foreground, [10, 25, 50, 75, 90])
    if p75 - p25 > max(.12, .08 * median) or p90 - p10 > max(.25, .15 * median):
        result["reason"] = "torso_depth_spread_too_large"
        return result
    # Locate the foreground's actual pixels instead of assuming the whole box centre.
    selected = mask & (patch >= p10) & (patch <= p90)
    xx = np.nonzero(selected)[1]
    u = float(np.median(xx) + left)
    bearing = math.atan2(u - cx, fx)  # optical convention: positive to image right
    result.update(valid=True, distance_m=round(float(median), 4),
                  bearing_rad=float(bearing), horizontal_m=float(median * (u - cx) / fx),
                  depth_spread_m=round(float(p90 - p10), 4), reason="ok")
    return result


def estimate_stereo_person_geometry(depth_m, bbox, intrinsics, skew_s=0.):
    """Approximate visible-body range from sparse stereo; never a motion permit.

    Passive stereo has holes, so the Orbbec torso density requirement would
    reject useful readings. This uses only the middle of a current body box and
    rejects weak coverage or multiple competing depth layers. A cropped head
    does not invalidate visible legs, but their range remains approximate.
    """
    result = dict(valid=False, distance_m=None, bearing_rad=None,
                  reason='invalid_depth', source='stereo_visible_body_approximate')
    depth = np.asarray(depth_m)
    if depth.ndim != 2 or not np.issubdtype(depth.dtype, np.floating):
        result['reason'] = 'depth_must_be_float_metres'
        return result
    if not math.isfinite(skew_s) or abs(skew_s) > .12:
        result['reason'] = 'rgb_depth_not_synchronized'
        return result
    try:
        fx, cx = float(intrinsics['fx']), float(intrinsics['cx'])
        if not math.isfinite(fx) or fx <= 0 or not math.isfinite(cx):
            raise ValueError()
        h, w = depth.shape
        x1, y1, x2, y2 = _box(bbox, w, h)
    except (ValueError, TypeError, KeyError, AttributeError):
        result['reason'] = 'invalid_geometry_inputs'
        return result
    bw, bh = x2 - x1, y2 - y1
    left, right = int(x1 + .25*bw), int(math.ceil(x1 + .75*bw))
    # At the robot's low camera height, the lower visible body/legs are more
    # consistently textured than the chest, which often overlaps background.
    top, bottom = int(y1 + .55*bh), int(math.ceil(y1 + .90*bh))
    patch = depth[top:bottom, left:right]
    mask = np.isfinite(patch) & (patch >= .3) & (patch <= 4.)
    count = int(mask.sum())
    fraction = count/max(1, patch.size)
    result.update(depth_roi=[left, top, right, bottom], valid_pixels=count,
                  valid_fraction=round(fraction, 3))
    if count < 120 or fraction < .25:
        result['reason'] = 'insufficient_stereo_body_depth'
        return result
    values = np.sort(patch[mask])
    clusters = np.split(values, np.flatnonzero(np.diff(values) > .10) + 1)
    substantial = [cluster for cluster in clusters if len(cluster) >= max(60, .25*count)]
    if not substantial:
        result['reason'] = 'incoherent_stereo_body_depth'
        return result
    foreground = substantial[0]
    support = len(foreground)/count
    if support < .55:
        result['reason'] = 'ambiguous_depth_layers'
        return result
    p10, p25, median, p75, p90 = np.percentile(foreground, [10, 25, 50, 75, 90])
    if p90-p10 > max(.25, .18*median) or p75-p25 > max(.15, .10*median):
        # A forward leg or an arm can widen the full lower-body ROI while a
        # smaller central region still gives a coherent, nearby range. Never
        # accept the centre alone: it must agree with the broad ROI's nearest
        # substantial depth layer, so a wall visible between the legs cannot
        # become the person's distance.
        narrow_left, narrow_right = int(x1 + .38*bw), int(math.ceil(x1 + .62*bw))
        narrow_top, narrow_bottom = int(y1 + .55*bh), int(math.ceil(y1 + .85*bh))
        narrow = depth[narrow_top:narrow_bottom, narrow_left:narrow_right]
        narrow_mask = np.isfinite(narrow) & (narrow >= .3) & (narrow <= 4.)
        narrow_count = int(narrow_mask.sum())
        if narrow_count < 120 or narrow_count/max(1, narrow.size) < .4:
            result['reason'] = 'stereo_depth_spread_too_large'
            return result
        narrow_values = np.sort(narrow[narrow_mask])
        narrow_clusters = np.split(narrow_values, np.flatnonzero(np.diff(narrow_values) > .10) + 1)
        narrow_layers = [cluster for cluster in narrow_clusters if len(cluster) >= max(60, .25*narrow_count)]
        if not narrow_layers or len(narrow_layers[0])/narrow_count < .65:
            result['reason'] = 'stereo_depth_spread_too_large'
            return result
        inner_p10, inner_p25, inner_median, inner_p75, inner_p90 = np.percentile(
            narrow_layers[0], [10, 25, 50, 75, 90])
        if (inner_p90-inner_p10 > max(.32, .20*inner_median) or
                inner_p75-inner_p25 > max(.18, .12*inner_median) or
                not median-.35 <= inner_median <= median+.25):
            result['reason'] = 'stereo_depth_spread_too_large'
            return result
        patch, mask = narrow, narrow_mask
        left, top, right, bottom = narrow_left, narrow_top, narrow_right, narrow_bottom
        p10, median, p90 = inner_p10, inner_median, inner_p90
        result['depth_roi'] = [left, top, right, bottom]
        result['reason'] = 'ok_center_fallback'
    selected = mask & (patch >= p10) & (patch <= p90)
    pixels_x = np.nonzero(selected)[1]
    if len(pixels_x) < 60:
        result['reason'] = 'insufficient_stereo_body_depth'
        return result
    u = float(np.median(pixels_x) + left)
    bearing = math.atan2(u-cx, fx)
    result.update(valid=True, distance_m=round(float(median), 4),
                  bearing_rad=float(bearing), horizontal_m=float(median*(u-cx)/fx),
                  depth_spread_m=round(float(p90-p10), 4),
                  reason=result['reason'] if result['reason'] == 'ok_center_fallback' else 'ok')
    return result
