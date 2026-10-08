"""Load / save named waypoints yaml (map frame)."""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Tuple

import yaml

NAME_RE = re.compile(r'^[A-Za-z][A-Za-z0-9_]*$')


def default_waypoints_path() -> str:
    """Prefer install share, then source trees under ROS_WS / common homes."""
    candidates = []
    try:
        from ament_index_python.packages import get_package_share_directory
        share = get_package_share_directory('nav_llm_agent')
        candidates.append(os.path.join(share, 'config', 'waypoints.yaml'))
    except Exception:
        pass

    ws = os.environ.get('ROS_WS') or os.environ.get('COLCON_PREFIX_PATH', '').split(':')[0]
    if ws:
        # COLCON_PREFIX_PATH points at <ws>/install; strip to workspace root.
        root = ws[:-8] if ws.endswith('/install') else ws
        candidates.append(os.path.join(
            root, 'src', 'nav_llm_agent', 'config', 'waypoints.yaml'))

    home = os.environ.get('ROS_USER_HOME') or os.path.expanduser('~')
    for ws_name in ('ddsm_car_ws', 'ros2_ws'):
        candidates.append(os.path.join(
            home, ws_name, 'src', 'nav_llm_agent', 'config', 'waypoints.yaml'))

    candidates.append(
        '/home/yuxi/ros2_ws/src/nav_llm_agent/config/waypoints.yaml')
    candidates.append(
        '/home/sunrise/luka_ws/system/nav_llm_agent/config/waypoints.yaml')

    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return candidates[-1]


def load_waypoints(path: str) -> Tuple[str, Dict[str, Dict[str, Any]]]:
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    with open(path, 'r', encoding='utf-8') as handle:
        raw = yaml.safe_load(handle) or {}
    frame_id = str(raw.get('frame_id') or 'map')
    items = raw.get('waypoints') or {}
    waypoints: Dict[str, Dict[str, Any]] = {}
    for name, spec in items.items():
        aliases = [
            str(a).strip()
            for a in (spec.get('aliases') or [])
            if str(a).strip()
        ]
        waypoints[str(name)] = {
            'name': str(name),
            'x': float(spec['x']),
            'y': float(spec['y']),
            'yaw': float(spec.get('yaw', 0.0)),
            'aliases': aliases,
            'description': str(spec.get('description') or ''),
            'internal': bool(spec.get('internal', False)),
        }
    return frame_id, waypoints


def save_waypoints(
        path: str,
        frame_id: str,
        waypoints: Dict[str, Dict[str, Any]]) -> None:
    payload = {
        'frame_id': frame_id,
        'waypoints': {},
    }
    for name, spec in waypoints.items():
        payload['waypoints'][name] = {
            'aliases': list(spec.get('aliases') or []),
            'x': float(spec['x']),
            'y': float(spec['y']),
            'yaw': float(spec.get('yaw', 0.0)),
            'description': str(spec.get('description') or ''),
            'internal': bool(spec.get('internal', False)),
        }
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8') as handle:
        handle.write(
            '# Named goals in the map frame. Coordinates must match the static map\n'
            '# used by Nav2. The LLM may only pick a waypoint name.\n')
        yaml.safe_dump(
            payload,
            handle,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False)


def upsert_waypoint(
        waypoints: Dict[str, Dict[str, Any]],
        name: str,
        aliases: List[str],
        x: float,
        y: float,
        yaw: float = 0.0,
        description: str = '') -> None:
    existing = waypoints.get(name) or {}
    waypoints[name] = {
        'name': name,
        'x': x,
        'y': y,
        'yaw': yaw,
        'aliases': aliases or list(existing.get('aliases') or []),
        'description': description or str(existing.get('description') or ''),
        'internal': bool(existing.get('internal', False)),
    }


def label_for(spec: Dict[str, Any]) -> str:
    """RViz TEXT markers: prefer ASCII name (Liberation Sans has no CJK glyphs)."""
    name = str(spec.get('name') or '').strip()
    if name:
        return name
    for alias in spec.get('aliases') or []:
        if alias:
            return str(alias)
    return ''
