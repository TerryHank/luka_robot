"""Loopback proxy for static people monitoring, not a motion API."""
import json
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError

GETS = {'status', 'frame.jpg'}
POSTS = {'start', 'stop', 'select', 'unlock', 'enroll', 'cancel-enrollment',
         'finish-enrollment', 'delete-profile'}


def handle(handler, post=False):
    path = urlparse(handler.path).path
    action = path.removeprefix('/api/people/')
    if action not in (POSTS if post else GETS):
        handler.send_json({'error': '此接口仅支持静态人体识别，不执行跟随运动'}, 404)
        return
    try:
        data = None
        if post:
            origin = handler.headers.get('Origin')
            if origin and urlparse(origin).netloc != handler.headers.get('Host'):
                return handler.send_json({'error': '请从小车监控页面操作'}, 403)
            size = int(handler.headers.get('Content-Length', '0'))
            if not 0 <= size <= 4096:
                raise ValueError('请求过大')
            data = handler.rfile.read(size) or b'{}'
            if not isinstance(json.loads(data), dict):
                raise ValueError('请求格式无效')
        request = Request('http://127.0.0.1:8097/api/people/' + action, data=data,
                          headers={'Content-Type': 'application/json'})
        with urlopen(request, timeout=3) as response:
            body = response.read(2_000_001)
            if len(body) > 2_000_000:
                raise ValueError('响应过大')
            handler.send_bytes(body, response.headers.get('Content-Type', 'application/json'))
    except HTTPError as exc:
        try:
            body = json.loads(exc.read(8192))
        except (ValueError, OSError):
            body = {'error': '识别服务暂不可用'}
        handler.send_json(body, exc.code)
    except ValueError as exc:
        handler.send_json({'error': str(exc)}, 400)
    except Exception:
        handler.send_json({'error': '人体识别服务未就绪，请稍后重试'}, 503)
