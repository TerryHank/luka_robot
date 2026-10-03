"""Short-lease, hold-to-drive HTTP bridge for the S100 development console."""
import json
import math
import secrets
import threading
import time
from urllib.parse import urlparse

from geometry_msgs.msg import Twist
from std_msgs.msg import String


GEARS = (
    {'name': '1/5 档', 'forward': .40, 'back': -.40, 'side': .40, 'turn': .80},
    {'name': '2/5 档', 'forward': .50, 'back': -.50, 'side': .50, 'turn': 1.00},
    {'name': '3/5 档', 'forward': .60, 'back': -.60, 'side': .60, 'turn': 1.20},
    {'name': '4/5 档', 'forward': .70, 'back': -.70, 'side': .70, 'turn': 1.40},
    {'name': '5/5 档', 'forward': .80, 'back': -.80, 'side': .80, 'turn': 1.60},
)
DIRECTIONS = ('forward', 'back', 'left', 'right', 'turn_left', 'turn_right')


class WebTeleop:
    def __init__(self, node, stop_navigation):
        self.node = node
        self.stop_navigation = stop_navigation
        self.pub = node.create_publisher(Twist, '/nx/web_teleop_cmd_vel', 10)
        self.lock = threading.RLock()
        self.token = None
        self.lease_until = 0.0
        self.gear = 0
        self.base_status = '底盘状态未收到'
        self.base_status_at = 0.0
        node.create_subscription(String, '/nx/web_teleop_status', self._on_status, 10)

    def _on_status(self, message):
        with self.lock:
            self.base_status = message.data
            self.base_status_at = time.monotonic()

    def _send(self, direction=None, axes=None):
        msg = Twist()
        if axes is not None:
            if not isinstance(axes, dict) or set(axes) != {'move_x', 'move_y', 'turn_x'}:
                raise ValueError('无效摇杆数据')
            try:
                mx, my, turn = (float(axes[key]) for key in ('move_x', 'move_y', 'turn_x'))
            except (TypeError, ValueError):
                raise ValueError('无效摇杆数据')
            if not all(math.isfinite(v) and -1 <= v <= 1 for v in (mx, my, turn)):
                raise ValueError('摇杆数值超出范围')
            length = math.hypot(mx, my)
            if length > 1:
                mx, my = mx / length, my / length
            def deadzone(v):
                return 0.0 if abs(v) < .10 else math.copysign((abs(v) - .10) / .90, v)
            mx, my, turn = deadzone(mx), deadzone(my), deadzone(turn)
            speed = GEARS[self.gear]
            msg.linear.x = my * (speed['forward'] if my >= 0 else -speed['back'])
            msg.linear.y = -mx * speed['side']
            msg.angular.z = -turn * speed['turn']
        elif direction:
            speed = GEARS[self.gear]
            if direction == 'forward': msg.linear.x = speed['forward']
            elif direction == 'back': msg.linear.x = speed['back']
            elif direction == 'left': msg.linear.y = speed['side']
            elif direction == 'right': msg.linear.y = -speed['side']
            elif direction == 'turn_left': msg.angular.z = speed['turn']
            elif direction == 'turn_right': msg.angular.z = -speed['turn']
        self.pub.publish(msg)

    def force_stop(self):
        with self.lock:
            self.token = None
            self.lease_until = 0.0
            self._send()

    def status(self):
        with self.lock:
            now = time.monotonic()
            return {
                'ok': True,
                'session_active': bool(self.token and now < self.lease_until),
                'base_online': now - self.base_status_at < 1.2,
                'base_status': self.base_status if now - self.base_status_at < 1.2 else '底盘状态过期',
                'gear': self.gear + 1,
                'gear_name': GEARS[self.gear]['name'],
                'speed_m_s': GEARS[self.gear]['forward'],
            }

    @staticmethod
    def _body(handler):
        size = int(handler.headers.get('Content-Length', '0'))
        if not 0 <= size <= 256:
            raise ValueError('请求过大')
        return json.loads(handler.rfile.read(size) or b'{}')

    @staticmethod
    def _origin_ok(handler, path):
        if path.endswith('/stop'):
            return True  # A stop request may be sent with sendBeacon on page exit.
        if handler.headers.get('X-Luka-Control') != 'hold-to-drive':
            return False
        origin = handler.headers.get('Origin')
        return not origin or urlparse(origin).netloc == handler.headers.get('Host')

    def handle_post(self, handler, path):
        if not self._origin_ok(handler, path):
            return handler.send_json({'error': '来源校验失败'}, 403)
        try:
            body = self._body(handler)
            now = time.monotonic()
            if path.endswith('/start'):
                with self.lock:
                    if self.token and now < self.lease_until:
                        raise ValueError('另一页面正在遥控；请先松开按钮')
                    if now - self.base_status_at >= 1.2:
                        raise ValueError('底盘未在线，不能遥控')
                self.stop_navigation()
                self.node.follow_controller.stop('网页遥控接管')
                self.node.relocalization.stop_rotation()
                self.node.patrol_mission.cancel.set()
                with self.lock:
                    self.token = secrets.token_urlsafe(24)
                    self.lease_until = time.monotonic() + 5.0
                    self._send()
                    token = self.token
                return handler.send_json({'ok': True, 'token': token})
            if path.endswith('/pulse'):
                direction = body.get('direction')
                axes = body.get('axes')
                if axes is None and direction not in DIRECTIONS:
                    raise ValueError('无效方向')
                with self.lock:
                    if not self.token or body.get('token') != self.token or now >= self.lease_until:
                        raise ValueError('遥控会话已结束，请重新按住按钮')
                    self.lease_until = now + 1.0
                    self._send(direction if axes is None else None, axes)
                return handler.send_json({'ok': True})
            if path.endswith('/gear'):
                with self.lock:
                    if self.token and now < self.lease_until:
                        raise ValueError('请先松开方向按钮再调速')
                    self._send()
                    self.gear = (self.gear + 1) % len(GEARS)
                    gear = self.gear
                return handler.send_json({'ok': True, 'gear': gear + 1,
                                          'gear_name': GEARS[gear]['name'],
                                          'speed_m_s': GEARS[gear]['forward']})
            if path.endswith('/stop'):
                with self.lock:
                    if body.get('token') == self.token:
                        self.token = None
                        self.lease_until = 0.0
                    self._send()
                return handler.send_json({'ok': True})
            return handler.send_json({'error': '未知遥控操作'}, 404)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            return handler.send_json({'error': str(exc)}, 409)
