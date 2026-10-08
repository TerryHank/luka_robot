#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import cv2
import numpy as np
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import (
    DurabilityPolicy,
    HistoryPolicy,
    QoSProfile,
    ReliabilityPolicy,
)
from sensor_msgs.msg import Image, CompressedImage
from std_msgs.msg import String


FRAME_FILE = Path("/tmp/ddsm_semantic_annotated.jpg")
DETECTION_FILE = Path("/tmp/ddsm_semantic_detection.jpg")
STATUS_FILE = Path("/tmp/ddsm_semantic_status.json")
HTTP_PORT = int(os.environ.get("VISION_HTTP_PORT", "8502"))
PREVIEW_RATE = max(1.0, float(os.environ.get("VISION_PREVIEW_RATE", "4.0")))
SEMANTIC_STALE_SECONDS = 15.0  # Current inference runs at 0.2 Hz.
WRITE_LOCK = threading.Lock()


def atomic_write(path: Path, data: bytes) -> None:
    with WRITE_LOCK:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(data)
        os.replace(temporary, path)


class VisionRequestHandler(BaseHTTPRequestHandler):
    def send_file(self, path: Path, content_type: str) -> None:
        if not path.exists():
            self.send_error(404)
            return
        if time.time() - path.stat().st_mtime > 5.0:
            self.send_error(503, "Vision data stale")
            return
        payload = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        request_path = urlparse(self.path).path
        if request_path == "/frame.jpg":
            self.send_file(FRAME_FILE, "image/jpeg")
        elif request_path == "/detection.jpg":
            self.send_file(DETECTION_FILE, "image/jpeg")
        elif request_path == "/status.json":
            self.send_file(STATUS_FILE, "application/json; charset=utf-8")
        else:
            self.send_error(404)

    def log_message(self, format: str, *args: object) -> None:
        return


class VisionFrontendBridge(Node):
    def __init__(self) -> None:
        super().__init__("robot_tuning_ui_vision_bridge")
        self.semantic_status = "等待视觉识别状态"
        self.last_width = 0
        self.last_height = 0
        self.last_preview_time = 0.0
        self.last_semantic_time = 0.0
        self.last_camera_time = 0.0
        image_qos = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
        )
        self.create_subscription(
            Image,
            "/semantic_mapping/annotated_image",
            self.detection_callback,
            image_qos,
        )
        preview_qos = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
        )
        self.create_subscription(
            CompressedImage,
            "/camera/color/image_raw/compressed",
            self.compressed_preview_callback,
            preview_qos,
        )
        self.create_subscription(
            String,
            "/semantic_mapping/status",
            self.status_callback,
            10,
        )
        self.write_status()
        self.create_timer(1.0, self.write_status)

    def compressed_preview_callback(self, message):
        now = time.monotonic()
        if now - self.last_preview_time < 1.0 / PREVIEW_RATE:
            return
        self.last_preview_time = now
        age = time.time() - message.header.stamp.sec - message.header.stamp.nanosec / 1e9
        if not -0.2 <= age <= 2.0:
            return
        payload = bytes(message.data)
        if not self.last_width:
            decoded = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
            if decoded is None:
                return
            self.last_height, self.last_width = decoded.shape[:2]
        self.last_camera_time = time.time()
        atomic_write(FRAME_FILE, payload)
        if time.time() - self.last_semantic_time > SEMANTIC_STALE_SECONDS:
            atomic_write(DETECTION_FILE, payload)

    def write_status(self) -> None:
        now = time.time()
        semantic_age = (
            now - self.last_semantic_time if self.last_semantic_time > 0.0 else None
        )
        status_fresh = semantic_age is not None and semantic_age <= SEMANTIC_STALE_SECONDS
        semantic_online = status_fresh and self.semantic_status.startswith("running")
        semantic_status = (
            self.semantic_status
            if status_fresh
            else "视觉识别离线或结果停更（当前不是识别结果）"
        )
        payload = json.dumps(
            {
                "semantic_status": semantic_status,
                "semantic_online": semantic_online,
                "semantic_age": semantic_age,
                "camera_online": now - self.last_camera_time <= 3.0,
                "width": self.last_width,
                "height": self.last_height,
                "updated_at": now,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        atomic_write(STATUS_FILE, payload)

    def status_callback(self, message: String) -> None:
        self.semantic_status = message.data or "视觉识别节点已连接"
        self.last_semantic_time = time.time()
        self.write_status()

    @staticmethod
    def encode_image(message: Image) -> tuple[bytes, int, int]:
        height = int(message.height)
        width = int(message.width)
        step = int(message.step)
        raw = np.frombuffer(bytes(message.data), dtype=np.uint8)
        rows = raw[: height * step].reshape(height, step)
        encoding = message.encoding.lower()

        if encoding in ("bgr8", "rgb8"):
            image = rows[:, : width * 3].reshape(height, width, 3)
            if encoding == "rgb8":
                image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        elif encoding in ("mono8", "8uc1"):
            image = rows[:, :width].reshape(height, width)
        else:
            raise ValueError(f"unsupported image encoding: {message.encoding}")

        encoded_ok, encoded = cv2.imencode(
            ".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 85]
        )
        if not encoded_ok:
            raise RuntimeError("JPEG encoding failed")
        return encoded.tobytes(), width, height

    def preview_callback(self, message: Image) -> None:
        now = time.monotonic()
        if now - self.last_preview_time < 1.0 / PREVIEW_RATE:
            return
        self.last_preview_time = now
        try:
            payload, self.last_width, self.last_height = self.encode_image(message)
            atomic_write(FRAME_FILE, payload)
            if time.time() - self.last_semantic_time > SEMANTIC_STALE_SECONDS:
                atomic_write(DETECTION_FILE, payload)
            self.write_status()
        except Exception as exc:
            self.semantic_status = f"实时画面转换失败：{exc}"
            self.write_status()

    def detection_callback(self, message: Image) -> None:
        try:
            payload, _, _ = self.encode_image(message)
            # Preview frames are not proof that inference is still completing.
            atomic_write(DETECTION_FILE, payload)
            self.write_status()
        except Exception as exc:
            self.semantic_status = f"识别结果转换失败：{exc}"
            self.write_status()


class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def main() -> None:
    node = None
    server = None
    rclpy.init()
    try:
        node = VisionFrontendBridge()
        server = ReusableThreadingHTTPServer(
            ("0.0.0.0", HTTP_PORT), VisionRequestHandler
        )
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        try:
            rclpy.spin(node)
        except (ExternalShutdownException, KeyboardInterrupt):
            pass
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
