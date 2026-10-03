#!/usr/bin/env python3
"""Small mecanum dance demo for ROS 2 Twist-based bases."""

import argparse
import math
import signal
import sys
import time
from dataclasses import dataclass

import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node


@dataclass(frozen=True)
class Move:
    name: str
    duration: float
    vx: float = 0.0
    vy: float = 0.0
    wz: float = 0.0


def clamp(value: float, limit: float) -> float:
    return max(-limit, min(limit, value))


def ease(progress: float, ramp_fraction: float = 0.18) -> float:
    """Return a smooth envelope with ramp up and ramp down."""
    if progress <= 0.0 or progress >= 1.0:
        return 0.0
    ramp_fraction = max(0.01, min(0.45, ramp_fraction))
    if progress < ramp_fraction:
        x = progress / ramp_fraction
        return 0.5 - 0.5 * math.cos(math.pi * x)
    if progress > 1.0 - ramp_fraction:
        x = (1.0 - progress) / ramp_fraction
        return 0.5 - 0.5 * math.cos(math.pi * x)
    return 1.0


def build_demo_moves() -> list[Move]:
    return [
        Move("wake-left", 0.9, vy=0.16),
        Move("wake-right", 0.9, vy=-0.16),
        Move("bow-forward", 0.8, vx=0.14),
        Move("bow-back", 0.8, vx=-0.14),
        Move("orbit-left", 1.5, vx=0.10, vy=0.12, wz=0.55),
        Move("orbit-right", 1.5, vx=0.10, vy=-0.12, wz=-0.55),
        Move("slide-left", 1.1, vy=0.20),
        Move("slide-right", 1.1, vy=-0.20),
        Move("spin-clockwise", 1.1, wz=0.75),
        Move("spin-counter", 1.1, wz=-0.75),
        Move("diagonal-a", 0.9, vx=0.13, vy=0.13),
        Move("diagonal-b", 0.9, vx=-0.13, vy=-0.13),
        Move("finale-sweep-left", 1.2, vx=0.08, vy=0.18, wz=0.45),
        Move("finale-sweep-right", 1.2, vx=0.08, vy=-0.18, wz=-0.45),
    ]


class DanceDemo(Node):
    def __init__(self, topic: str, hz: float, dry_run: bool) -> None:
        super().__init__("mecanum_dance_demo")
        self.publisher = self.create_publisher(Twist, topic, 10)
        self.topic = topic
        self.period = 1.0 / hz
        self.dry_run = dry_run

    def publish_twist(self, vx: float, vy: float, wz: float) -> None:
        if self.dry_run:
            return
        msg = Twist()
        msg.linear.x = vx
        msg.linear.y = vy
        msg.angular.z = wz
        self.publisher.publish(msg)

    def stop(self) -> None:
        for _ in range(8):
            self.publish_twist(0.0, 0.0, 0.0)
            time.sleep(0.03)

    def run_move(
        self,
        move: Move,
        scale: float,
        forward_sign: float,
        lateral_sign: float,
        angular_sign: float,
    ) -> None:
        start = time.monotonic()
        end = start + move.duration
        self.get_logger().info(f"dance move: {move.name}")
        while rclpy.ok() and time.monotonic() < end:
            now = time.monotonic()
            progress = (now - start) / move.duration
            k = ease(progress)
            vx = move.vx * scale * forward_sign * k
            vy = move.vy * scale * lateral_sign * k
            wz = move.wz * scale * angular_sign * k
            self.publish_twist(vx, vy, wz)
            rclpy.spin_once(self, timeout_sec=0.0)
            time.sleep(self.period)
        self.stop()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a safe mecanum chassis dance demo.")
    parser.add_argument("--topic", default="/cmd_vel_nav", help="Twist command topic.")
    parser.add_argument("--hz", type=float, default=30.0, help="Publish frequency.")
    parser.add_argument("--scale", type=float, default=1.0, help="Speed scale, e.g. 0.5 for half speed.")
    parser.add_argument("--repeat", type=int, default=1, help="Number of dance loops.")
    parser.add_argument("--forward-sign", type=float, choices=(-1.0, 1.0), default=1.0)
    parser.add_argument("--lateral-sign", type=float, choices=(-1.0, 1.0), default=1.0)
    parser.add_argument("--angular-sign", type=float, choices=(-1.0, 1.0), default=1.0)
    parser.add_argument("--dry-run", action="store_true", help="Print moves without publishing motion.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    scale = max(0.0, min(1.0, args.scale))
    if args.repeat < 1:
        print("--repeat must be >= 1", file=sys.stderr)
        return 2

    moves = build_demo_moves()
    if args.dry_run:
        total = sum(move.duration for move in moves) * args.repeat
        print(f"topic={args.topic} hz={args.hz:.1f} scale={scale:.2f} total={total:.1f}s")
        for move in moves:
            print(move)
        return 0

    rclpy.init()
    node = DanceDemo(args.topic, max(5.0, args.hz), args.dry_run)

    stop_requested = False

    def handle_signal(signum, frame):
        nonlocal stop_requested
        stop_requested = True
        node.stop()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        node.get_logger().info(
            "starting mecanum dance demo; keep a clear 2m x 2m area and be ready to stop"
        )
        for _ in range(args.repeat):
            for move in moves:
                if stop_requested or not rclpy.ok():
                    break
                node.run_move(move, scale, args.forward_sign, args.lateral_sign, args.angular_sign)
        node.stop()
        node.get_logger().info("dance demo finished")
    finally:
        node.stop()
        node.destroy_node()
        rclpy.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
