#!/usr/bin/env python3

from __future__ import annotations

import sys
import threading
from typing import Optional

import rclpy
from geometry_msgs.msg import PointStamped
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import Empty

from nav_llm_agent.waypoint_store import (
    NAME_RE,
    default_waypoints_path,
    load_waypoints,
    save_waypoints,
    upsert_waypoint,
)

TRANSIENT = QoSProfile(
    depth=1,
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    history=HistoryPolicy.KEEP_LAST,
)


class SaveWaypoint(Node):
    def __init__(self):
        super().__init__('save_waypoint')
        self.declare_parameter('waypoints_file', default_waypoints_path())
        self._path = str(self.get_parameter('waypoints_file').value)
        self._click: Optional[PointStamped] = None
        self._event = threading.Event()
        self._reload_pub = self.create_publisher(Empty, '/waypoints_reload', 10)
        self.create_subscription(
            PointStamped, '/waypoint_last_click', self._on_click, TRANSIENT)
        self.create_subscription(
            PointStamped, '/clicked_point', self._on_click, 10)

    def _on_click(self, msg: PointStamped) -> None:
        self._click = msg
        self._event.set()

    def wait_for_click(self, cache_sec: float = 0.8) -> PointStamped:
        if self._event.wait(timeout=cache_sec) and self._click is not None:
            return self._click
        print(
            '还没有缓存的点击。请在 RViz 工具栏选 Publish Point（发布点），'
            '再在地图上空地点一下（不要用 2D Goal Pose）。',
            flush=True,
        )
        self._event.clear()
        if not self._event.wait(timeout=120.0) or self._click is None:
            raise TimeoutError('等待 /clicked_point 超时')
        return self._click


def _prompt(label: str) -> str:
    try:
        return input(label).strip()
    except EOFError as exc:
        raise RuntimeError('无法从终端读入（请用独立终端 ros2 run，不要放进 launch）') from exc


def _spin_bg(node: SaveWaypoint):
    rclpy.spin(node)


def main(args=None):
    rclpy.init(args=args)
    node = SaveWaypoint()
    spinner = threading.Thread(target=_spin_bg, args=(node,), daemon=True)
    spinner.start()
    try:
        click = node.wait_for_click()
        x = float(click.point.x)
        y = float(click.point.y)
        print(f'已记录点击 ({x:.3f}, {y:.3f}) frame={click.header.frame_id or "map"}', flush=True)
        name = _prompt('英文键（yaml name，如 kitchen）: ')
        if not NAME_RE.match(name):
            raise RuntimeError('英文键必须以字母开头，只能含字母数字下划线')
        alias_raw = _prompt('中文别名（如 厨房，多个用逗号分隔）: ')
        aliases = [part.strip() for part in alias_raw.replace('，', ',').split(',') if part.strip()]
        if not aliases:
            aliases = [name]
        try:
            frame_id, waypoints = load_waypoints(node._path)
        except FileNotFoundError:
            frame_id, waypoints = 'map', {}
        existed = name in waypoints
        upsert_waypoint(waypoints, name, aliases, x, y, yaw=0.0)
        save_waypoints(node._path, frame_id, waypoints)
        node._reload_pub.publish(Empty())
        action = '更新' if existed else '新增'
        print(
            f'{action}航点 {name} aliases={aliases} -> ({x:.3f}, {y:.3f})\n'
            f'已写入 {node._path} 并通知 /waypoints_reload',
            flush=True,
        )
    except (TimeoutError, RuntimeError, FileNotFoundError) as exc:
        print(f'错误: {exc}', file=sys.stderr, flush=True)
        node.destroy_node()
        rclpy.shutdown()
        raise SystemExit(1) from exc
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
