"""Geometry checks for a very short, direction-aware escape translation.

This module makes no motor commands. Every call uses fresh scan points in the
base_link frame. It treats a contact already near the body as recoverable only
when the proposed movement increases its clearance throughout the sweep.
"""

import math

HALF_LENGTH = .31  # 0.28 m body plus 0.03 m padding
HALF_WIDTH = .22   # 0.19 m body plus 0.03 m padding
CHECK_RADIUS = 1.2
MIN_NEW_CLEARANCE = .05
MAX_STEP = .01


def signed_clearance(x, y):
    """Distance to the padded rectangle; negative means inside it."""
    dx = abs(x) - HALF_LENGTH
    dy = abs(y) - HALF_WIDTH
    return math.hypot(max(dx, 0.), max(dy, 0.)) + min(max(dx, dy), 0.)


def check_translation(points, dx, dy, max_distance=.06):
    """Return a fail-closed decision for a bounded body-frame translation.

    ``dx`` and ``dy`` are where the robot moves, not where obstacles move.
    An already close point may remain close only if the body moves away from it.
    """
    if not all(math.isfinite(v) for v in (dx, dy)):
        return {'safe': False, 'reason': '位移无效'}
    length = math.hypot(dx, dy)
    if not .001 <= length <= max_distance:
        return {'safe': False, 'reason': '脱困位移超出限制'}
    if not points:
        return {'safe': False, 'reason': '雷达没有有效回波'}
    checked = 0
    close = 0
    minimum = float('inf')
    steps = math.ceil(length / MAX_STEP)
    for x, y in points:
        if not all(math.isfinite(v) for v in (x, y)):
            continue
        if x*x+y*y > CHECK_RADIUS*CHECK_RADIUS:
            continue
        checked += 1
        before = signed_clearance(x, y)
        minimum = min(minimum, before)
        if before < MIN_NEW_CLEARANCE:
            close += 1
        for i in range(1, steps+1):
            fraction = i / steps
            current = signed_clearance(x-dx*fraction, y-dy*fraction)
            if before >= MIN_NEW_CLEARANCE:
                if current < MIN_NEW_CLEARANCE:
                    return {'safe': False, 'reason': '脱困方向出现新的近距离障碍',
                            'point': (round(x, 3), round(y, 3))}
            elif current < before-.002:
                return {'safe': False, 'reason': '脱困使贴身障碍更近',
                        'point': (round(x, 3), round(y, 3))}
    if checked < 20:
        return {'safe': False, 'reason': '有效雷达点不足'}
    return {'safe': True, 'reason': '整车扫掠没有逼近障碍',
            'checked_points': checked, 'near_body_points': close,
            'minimum_initial_clearance_m': round(minimum, 3)}


def choose_escape(points):
    """Prefer straight retreat; consider lateral movement only if it is safer."""
    options = [('back', -.05, 0.), ('left', 0., .04), ('right', 0., -.04)]
    decisions = [(name, dx, dy, check_translation(points, dx, dy))
                 for name, dx, dy in options]
    for name, dx, dy, decision in decisions:
        if decision['safe']:
            return {'safe': True, 'direction': name, 'dx': dx, 'dy': dy,
                    'distance_m': round(math.hypot(dx, dy), 3),
                    'checks': {n: d for n, _, _, d in decisions}}
    return {'safe': False, 'reason': '后退和侧移都没有安全通道',
            'checks': {n: d for n, _, _, d in decisions}}
