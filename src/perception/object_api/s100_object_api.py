"""Person-only detector API using the supplied YOLO26 segmentation model.

This deliberately advertises only classes the model supports. It does not
pretend to provide the NX's open-vocabulary NanoOWL/YOLOE behavior.
"""

from base64 import b64decode
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
import json
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'person_follow'))
from yolo26_person import Yolo26PersonSegmenter, MODEL, HBM
NAMES = ['person']
ALIASES = {'人': 'person', '人体': 'person', '人员': 'person'}


class Detector:
    def __init__(self):
        self.model = Yolo26PersonSegmenter(confidence=.30)
        self.runtime_backend = getattr(self.model, 'backend_name', 'legacy')
        self.runtime_fallback_reason = getattr(
            self.model, 'fallback_reason', None)
        self.lock = Lock()

    def infer(self, image):
        with self.lock:
            results = self.model.detect(image)
        return [{key: row[key] for key in ('class', 'confidence', 'bbox')}
                for row in results]


detector = None
detector_lock = Lock()


class Handler(BaseHTTPRequestHandler):
    def reply(self, body, status=200):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            return self.reply({
                "ok": True,
                "model_loaded": detector is not None,
                "backend": "yolo26m-objv1-seg-person-bpu",
                "runtime_backend_requested": __import__("os").getenv(
                    "NX_YOLO26_RUNTIME_BACKEND", "legacy"),
                "runtime_backend_active": (
                    detector.runtime_backend if detector is not None else None),
                "runtime_fallback_reason": (
                    detector.runtime_fallback_reason if detector is not None
                    else None),
                "classes": len(NAMES),
                "enabled_classes": NAMES,
                "model": MODEL,
                "runtime_model": str(HBM),
                "open_vocabulary": False,
            })
        self.reply({"error": "not found"}, 404)

    def do_POST(self):
        global detector
        if self.path == "/model/unload":
            with detector_lock:
                detector = None
            return self.reply({"ok": True})
        if self.path != "/infer_image":
            return self.reply({"error": "not found"}, 404)
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 12_000_000:
                raise ValueError("invalid request size")
            request = json.loads(self.rfile.read(size))
            raw = b64decode(request["image_base64"], validate=True)
            if len(raw) > 8_000_000:
                raise ValueError("image too large")
            image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
            if image is None or image.shape[0] * image.shape[1] > 8_000_000:
                raise ValueError("invalid image")
            query = str(request.get("query") or "").strip()
            target = ALIASES.get(query, query.lower())
            if query and target not in NAMES:
                return self.reply({"error": "unsupported_class", "query": query,
                                   "backend": "yolo26m-objv1-seg-person-bpu"}, 422)
            with detector_lock:
                if detector is None:
                    detector = Detector()
                active = detector
            started = time.monotonic()
            results = active.infer(image)
            if query:
                results = [row for row in results if row["class"] == target]
            return self.reply({
                "detections": results,
                "inference_seconds": round(time.monotonic() - started, 4),
                "backend": "yolo26m-objv1-seg-person-bpu",
                "runtime_backend": active.runtime_backend,
            })
        except (ValueError, KeyError, TypeError) as exc:
            self.reply({"error": str(exc)}, 400)
        except Exception as exc:
            self.reply({"error": type(exc).__name__}, 503)


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 8096), Handler).serve_forever()
