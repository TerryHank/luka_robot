"""YOLO26 person-only live camera search. No recording or motor control."""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parent
CAMERA = os.getenv("NX_CAMERA_SNAPSHOT_URL", "http://127.0.0.1:8091/snapshot-raw-left.jpg")
ALIASES = {
    "人": "person", "沙发": "sofa", "椅子": "chair", "办公椅": "chair",
    "桌子": "table", "餐桌": "table", "书桌": "desk", "床": "bed",
    "柜子": "cabinet", "橱柜": "cabinet", "书架": "bookshelf", "冰箱": "refrigerator",
    "冰柜": "refrigerator", "微波炉": "microwave", "烤箱": "oven",
    "洗衣机": "washing machine", "空调": "air conditioner", "风扇": "fan",
    "电视": "television", "电脑": "computer", "显示器": "monitor",
    "吸尘器": "vacuum cleaner", "瓶子": "bottle", "矿泉水瓶": "bottle",
    "杯子": "cup", "水杯": "cup", "玻璃杯": "glass", "碗": "bowl",
    "盘子": "plate", "叉子": "fork", "刀": "knife", "勺子": "spoon",
    "水壶": "kettle", "锅": "pot", "烤面包机": "toaster", "马桶": "toilet",
    "洗手池": "sink", "水槽": "sink", "浴缸": "bathtub", "淋浴": "shower",
    "镜子": "mirror", "毛巾": "towel", "肥皂": "soap", "牙刷": "toothbrush",
    "剪刀": "scissors", "电线": "wire", "书": "book", "包": "bag",
    "背包": "backpack", "钥匙": "keys", "钱包": "wallet", "手机": "phone",
    "遥控器": "remote control", "钟": "clock", "时钟": "clock",
    "雨伞": "umbrella", "鞋": "shoe", "衣服": "clothes", "垃圾桶": "trash can",
    "门": "door", "窗": "window", "窗户": "window", "窗帘": "curtain",
    "灯": "light", "灭火器": "fire extinguisher",
}


def iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    aa = max(0, a[2] - a[0]) * max(0, a[3] - a[1])
    bb = max(0, b[2] - b[0]) * max(0, b[3] - b[1])
    return intersection / max(1, aa + bb - intersection)


class LiveSearch:
    def __init__(self):
        self.guard = threading.Lock()
        self.stop_event = threading.Event()
        self.thread = None
        self.session = None
        self.names = {}
        self.query = ""
        self.target = None
        self.running = False
        self.frames = 0
        self.captured_at = None
        self.completed_at = None
        self.inference_seconds = None
        self.image_size = None
        self.tiles = 0
        self.detections = []
        self.error = None
        self.jpeg = None
        self.previous = []

    def load(self):
        if self.session is not None:
            return
        self.session = True
        self.names = {0: 'person'}

    def supported(self):
        self.load()
        return list(self.names.values())

    def start(self, query):
        query = str(query or "").strip()
        if not query or len(query) > 100 or any(ord(c) < 32 for c in query):
            raise ValueError("请输入要找的物品，或输入‘全部’")
        self.load()
        target = None if query in ("全部", "所有", "all", "*") else ALIASES.get(query, query.lower())
        if target is not None and target not in self.names.values():
            raise ValueError("当前仅启用 person（人）类别")
        with self.guard:
            if self.running:
                raise ValueError("实时检索正在运行；请先停止，再更换目标")
            self.stop_event.clear()
            self.running = True
            self.query = query
            self.target = target
            self.frames = 0
            self.captured_at = None
            self.completed_at = None
            self.inference_seconds = None
            self.image_size = None
            self.tiles = 0
            self.detections = []
            self.jpeg = None
            self.error = None
            self.previous = []
            self.thread = threading.Thread(target=self.run, daemon=True)
            self.thread.start()
        return self.status()

    def stop(self):
        self.stop_event.set()
        with self.guard:
            self.running = False
            self.detections = []
            self.jpeg = None
        return self.status()

    def status(self):
        with self.guard:
            return {"running": self.running, "query": self.query,
                    "target": self.target, "frames": self.frames,
                    "captured_at": self.captured_at, "completed_at": self.completed_at,
                    "inference_seconds": self.inference_seconds,
                    "image_size": self.image_size, "tiles": self.tiles,
                    "detections": list(self.detections), "error": self.error,
                    "backend": "YOLO26m objv1 person-only S100 BPU", "vocabulary_size": len(self.names)}

    def infer_tile(self, image, x_offset, y_offset):
        """Run a native-pixel 640-square tile; never resize the camera frame."""
        tile = image[y_offset:y_offset + 640, x_offset:x_offset + 640]
        import base64
        ok, encoded = cv2.imencode('.jpg', tile)
        if not ok:
            raise ValueError('Camera image encoding failed')
        payload = json.dumps({'query': 'person', 'image_base64':
            base64.b64encode(encoded.tobytes()).decode('ascii')}).encode()
        request = urllib.request.Request('http://127.0.0.1:8096/infer_image',
            data=payload, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.load(response)
        found = [{'label': row['class'], 'confidence': row['confidence'],
            'bbox': [row['bbox'][0]+x_offset, row['bbox'][1]+y_offset,
                     row['bbox'][2]+x_offset, row['bbox'][3]+y_offset]}
                 for row in result['detections']]
        return found, result['inference_seconds']

    def infer(self, image):
        height, width = image.shape[:2]
        x_last, y_last = max(0, width - 640), max(0, height - 640)
        positions = [(0, 0), (x_last, 0), (0, y_last), (x_last, y_last),
                     (x_last // 2, y_last // 2)]
        positions = list(dict.fromkeys(positions))
        found, elapsed = [], 0.0
        for x_offset, y_offset in positions:
            tile_found, tile_time = self.infer_tile(image, x_offset, y_offset)
            found.extend(tile_found)
            elapsed += tile_time
        # Adjacent tiles can see the same item. Keep the strongest box.
        unique = []
        for item in sorted(found, key=lambda row: row["confidence"], reverse=True):
            if not any(item["label"] == old["label"] and iou(item["bbox"], old["bbox"]) > 0.4 for old in unique):
                unique.append(item)
        found = unique[:40]
        # Two-frame confirmation reduces isolated false matches and flashing boxes.
        confirmed = [item for item in found if item["confidence"] >= 0.6 or any(
            item["label"] == old["label"] and iou(item["bbox"], old["bbox"]) >= 0.2
            for old in self.previous)]
        self.previous = found
        marked = image.copy()
        for item in confirmed:
            x1, y1, x2, y2 = item["bbox"]
            cv2.rectangle(marked, (x1, y1), (x2, y2), (65, 222, 111), 2)
            cv2.putText(marked, f"{item['label']} {item['confidence']:.2f}",
                        (x1, max(20, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX,
                        0.55, (65, 222, 111), 2, cv2.LINE_AA)
        ok, jpeg = cv2.imencode(".jpg", marked, [cv2.IMWRITE_JPEG_QUALITY, 88])
        if not ok:
            raise RuntimeError("标注画面编码失败")
        return confirmed, jpeg.tobytes(), elapsed, len(positions)

    def run(self):
        try:
            camera_failures = 0
            while not self.stop_event.is_set():
                try:
                    captured = time.time()
                    with urllib.request.urlopen(CAMERA, timeout=3) as response:
                        raw = response.read(3_000_000)
                    image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
                    if image is None:
                        raise RuntimeError("相机画面无法解码")
                    camera_failures = 0
                except Exception as exc:
                    camera_failures += 1
                    with self.guard:
                        self.error = "相机暂不可用，正在重连：" + str(exc)[:120]
                    if camera_failures >= 20:
                        raise RuntimeError("相机持续不可用，请检查视觉服务") from exc
                    self.stop_event.wait(0.5)
                    continue
                detections, jpeg, elapsed, tiles = self.infer(image)
                with self.guard:
                    if self.stop_event.is_set():
                        break
                    self.frames += 1
                    self.captured_at = captured
                    self.completed_at = time.time()
                    self.inference_seconds = round(elapsed, 3)
                    self.image_size = [image.shape[1], image.shape[0]]
                    self.tiles = tiles
                    self.detections = detections
                    self.jpeg = jpeg
                    self.error = None
                self.stop_event.wait(0.12)
        except Exception as exc:
            with self.guard:
                self.error = str(exc)[:200]
        finally:
            with self.guard:
                self.running = False


search = LiveSearch()
search.load()


class Handler(BaseHTTPRequestHandler):
    def reply(self, payload, code=200, mime="application/json; charset=utf-8"):
        body = json.dumps(payload, ensure_ascii=False).encode() if not isinstance(payload, bytes) else payload
        self.send_response(code)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/status":
            return self.reply(search.status())
        if path == "/classes":
            try:
                return self.reply({"backend": "YOLO26m objv1 person-only S100 BPU", "classes": search.supported()})
            except Exception as exc:
                return self.reply({"error": str(exc)}, 503)
        if path == "/frame.jpg":
            with search.guard:
                frame = search.jpeg
            return self.reply(frame, mime="image/jpeg") if frame else self.reply({"error": "等待首帧"}, 503)
        self.reply({"error": "not found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > 1024:
                raise ValueError("请求过大")
            payload = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(payload, dict):
                raise ValueError("请求格式无效")
            if path == "/start":
                return self.reply(search.start(payload.get("query")), 202)
            if path == "/stop":
                return self.reply(search.stop())
            self.reply({"error": "not found"}, 404)
        except ValueError as exc:
            self.reply({"error": str(exc)}, 400)
        except Exception as exc:
            self.reply({"error": str(exc)}, 503)


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(os.getenv("YOLOE26_PORT", "8099"))), Handler).serve_forever()
