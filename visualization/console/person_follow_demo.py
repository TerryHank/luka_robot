#!/usr/bin/env python3
"""Camera-based person following demo for a ROS 2 mecanum base.

This is intentionally standalone: it reads a V4L2 camera directly and publishes
Twist only when --drive is set. The first detector is OpenCV HOG, which is light
enough for RK3588 and needs no model files.
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from dataclasses import dataclass

import cv2
import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node
from std_msgs.msg import String


@dataclass
class Detection:
    x: int
    y: int
    w: int
    h: int
    score: float


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


class PersonFollower(Node):
    def __init__(self, args: argparse.Namespace) -> None:
        super().__init__("person_follow_demo")
        self.args = args
        self.cmd_pub = self.create_publisher(Twist, args.cmd_topic, 10)
        self.status_pub = self.create_publisher(String, "/person_follow/status", 10)
        self.last_detection_time = 0.0
        self.last_cmd_time = 0.0
        self.frame_count = 0

    def publish_status(self, payload: dict) -> None:
        msg = String()
        msg.data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        self.status_pub.publish(msg)

    def publish_cmd(self, vx: float, vy: float, wz: float) -> None:
        if not self.args.drive:
            return
        msg = Twist()
        msg.linear.x = float(vx)
        msg.linear.y = float(vy)
        msg.angular.z = float(wz)
        self.cmd_pub.publish(msg)
        self.last_cmd_time = time.monotonic()

    def stop(self) -> None:
        for _ in range(8):
            self.publish_cmd(0.0, 0.0, 0.0)
            time.sleep(0.025)


def open_camera(args: argparse.Namespace) -> cv2.VideoCapture:
    cap = cv2.VideoCapture(args.camera, cv2.CAP_V4L2)
    if not cap.isOpened():
        raise RuntimeError(f"cannot open camera {args.camera}")
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*args.fourcc))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
    cap.set(cv2.CAP_PROP_FPS, args.camera_fps)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return cap


def create_hog() -> cv2.HOGDescriptor:
    hog = cv2.HOGDescriptor()
    hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
    return hog


def find_person(hog: cv2.HOGDescriptor, frame, args: argparse.Namespace) -> Detection | None:
    scale = args.detect_scale
    detect_frame = frame
    if scale != 1.0:
        detect_frame = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

    rects, weights = hog.detectMultiScale(
        detect_frame,
        winStride=(8, 8),
        padding=(8, 8),
        scale=args.hog_pyramid_scale,
        hitThreshold=args.hit_threshold,
    )
    if len(rects) == 0:
        return None

    detections: list[Detection] = []
    inv = 1.0 / scale
    for (x, y, w, h), score in zip(rects, weights):
        x = int(x * inv)
        y = int(y * inv)
        w = int(w * inv)
        h = int(h * inv)
        if h < args.min_person_height:
            continue
        detections.append(Detection(x=x, y=y, w=w, h=h, score=float(score)))
    if not detections:
        return None
    return max(detections, key=lambda d: d.w * d.h)


def command_from_detection(det: Detection, frame_w: int, frame_h: int, args: argparse.Namespace) -> tuple[float, float, float, dict]:
    cx = det.x + det.w * 0.5
    x_error = (cx - frame_w * 0.5) / (frame_w * 0.5)
    height_ratio = det.h / max(1.0, float(frame_h))
    distance_error = args.target_height_ratio - height_ratio

    if abs(distance_error) <= args.distance_deadband:
        vx = 0.0
    else:
        vx = clamp(distance_error * args.forward_gain, -args.max_reverse, args.max_forward)

    if abs(x_error) <= args.center_deadband:
        vy = 0.0
        wz = 0.0
    else:
        # Person appears left: x_error < 0. With the usual mecanum convention,
        # moving right and turning left both bring the person toward image center.
        vy = clamp(-x_error * args.lateral_gain, -args.max_lateral, args.max_lateral)
        wz = clamp(-x_error * args.angular_gain, -args.max_angular, args.max_angular)

    vy *= args.lateral_sign
    wz *= args.angular_sign
    vx *= args.forward_sign

    if args.no_strafe:
        vy = 0.0
    if args.no_turn:
        wz = 0.0

    debug = {
        "person": {"x": det.x, "y": det.y, "w": det.w, "h": det.h, "score": round(det.score, 3)},
        "x_error": round(x_error, 3),
        "height_ratio": round(height_ratio, 3),
        "cmd": {"vx": round(vx, 3), "vy": round(vy, 3), "wz": round(wz, 3)},
    }
    return vx, vy, wz, debug


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Track and follow a person with a mecanum robot.")
    parser.add_argument("--camera", default="/dev/video1")
    parser.add_argument("--cmd-topic", default="/cmd_vel_nav")
    parser.add_argument("--drive", action="store_true", help="Actually publish cmd_vel. Omit for observe-only mode.")
    parser.add_argument("--frames", type=int, default=0, help="Stop after N frames; 0 means run forever.")
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--camera-fps", type=float, default=30.0)
    parser.add_argument("--fourcc", default="MJPG")
    parser.add_argument("--detect-scale", type=float, default=0.75)
    parser.add_argument("--hog-pyramid-scale", type=float, default=1.05)
    parser.add_argument("--hit-threshold", type=float, default=0.0)
    parser.add_argument("--min-person-height", type=int, default=80)
    parser.add_argument("--target-height-ratio", type=float, default=0.48)
    parser.add_argument("--distance-deadband", type=float, default=0.06)
    parser.add_argument("--center-deadband", type=float, default=0.10)
    parser.add_argument("--forward-gain", type=float, default=0.55)
    parser.add_argument("--lateral-gain", type=float, default=0.18)
    parser.add_argument("--angular-gain", type=float, default=0.45)
    parser.add_argument("--max-forward", type=float, default=0.22)
    parser.add_argument("--max-reverse", type=float, default=0.10)
    parser.add_argument("--max-lateral", type=float, default=0.12)
    parser.add_argument("--max-angular", type=float, default=0.45)
    parser.add_argument("--forward-sign", type=float, choices=(-1.0, 1.0), default=1.0)
    parser.add_argument("--lateral-sign", type=float, choices=(-1.0, 1.0), default=1.0)
    parser.add_argument("--angular-sign", type=float, choices=(-1.0, 1.0), default=1.0)
    parser.add_argument("--no-strafe", action="store_true")
    parser.add_argument("--no-turn", action="store_true")
    parser.add_argument("--lost-timeout", type=float, default=0.45)
    parser.add_argument("--print-every", type=int, default=10)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rclpy.init()
    node = PersonFollower(args)
    hog = create_hog()

    try:
        cap = open_camera(args)
    except Exception as exc:
        print(f"camera error: {exc}", file=sys.stderr)
        rclpy.shutdown()
        return 2

    stop_requested = False

    def handle_signal(signum, frame):
        nonlocal stop_requested
        stop_requested = True
        node.stop()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    node.get_logger().info(
        f"person follow started camera={args.camera} cmd_topic={args.cmd_topic} drive={args.drive}"
    )
    if not args.drive:
        node.get_logger().warn("observe-only mode: add --drive to move the robot")

    try:
        while rclpy.ok() and not stop_requested:
            ok, frame = cap.read()
            if not ok:
                node.publish_status({"state": "camera_read_failed"})
                node.stop()
                time.sleep(0.1)
                continue

            node.frame_count += 1
            det = find_person(hog, frame, args)
            now = time.monotonic()

            if det is None:
                if now - node.last_detection_time > args.lost_timeout:
                    node.publish_cmd(0.0, 0.0, 0.0)
                status = {"state": "searching", "frame": node.frame_count}
            else:
                node.last_detection_time = now
                vx, vy, wz, debug = command_from_detection(det, frame.shape[1], frame.shape[0], args)
                node.publish_cmd(vx, vy, wz)
                status = {"state": "tracking", "frame": node.frame_count, **debug}

            node.publish_status(status)
            if node.frame_count % max(1, args.print_every) == 0:
                print(json.dumps(status, ensure_ascii=False, separators=(",", ":")), flush=True)

            rclpy.spin_once(node, timeout_sec=0.0)
            if args.frames and node.frame_count >= args.frames:
                break
    finally:
        node.stop()
        cap.release()
        node.destroy_node()
        rclpy.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
