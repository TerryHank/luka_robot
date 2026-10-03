"""Local monitor supervisor. This service has no ROS or motor-control API."""
import json
import os
import signal
from pathlib import Path
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
DATA.mkdir(exist_ok=True)
def physical_budget_gib():
    """Leave headroom for the OS on the installed board, without a fixed 8GB cap."""
    try:
        total_kib = next(int(line.split()[1]) for line in Path('/proc/meminfo').read_text().splitlines()
                         if line.startswith('MemTotal:'))
        return round(max(4.0, total_kib / 1024**2 - 1.5), 2)
    except (OSError, StopIteration, ValueError):
        return 6.0


BUDGET_GIB = physical_budget_gib()


def memory():
    values = {line.split()[0].rstrip(':'): int(line.split()[1])
              for line in Path('/proc/meminfo').read_text().splitlines()}
    used = (values['MemTotal'] - values['MemAvailable']) / 1024**2
    return {'system_used_gib': round(used, 3), 'budget_gib': BUDGET_GIB,
            'swap_mib': round((values['SwapTotal'] - values['SwapFree']) / 1024, 1)}


def fetch(path, body=None, base='http://127.0.0.1:8091', timeout=1.5):
    request = Request(base + path, data=None if body is None else json.dumps(body).encode(),
                      headers={'Content-Type': 'application/json'})
    with urlopen(request, timeout=timeout) as response:
        raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError('响应超出大小限制')
        return raw, response.headers.get('Content-Type', 'application/json')


def visual_busy(camera_source='orbbec'):
    if camera_source not in ('orbbec', 'stereo_uvc', 'stereo_shared'):
        raise ValueError('未知人体识别相机来源')
    health = json.loads(fetch('/health')[0])
    semantic = json.loads(fetch('/semantic/status')[0])
    patrol = json.loads(fetch('/patrol/status')[0])
    return ((camera_source != 'stereo_uvc' and not health.get('camera_online')) or health.get('busy') or
            health.get('model_loaded') or health.get('tracking', {}).get('running') or
            semantic.get('running') or bool(patrol.get('recording')) or
            (patrol.get('job') or {}).get('status') == 'searching')


class Supervisor:
    def __init__(self):
        self.process = None
        self.lock = threading.RLock()
        self.started_at = 0
        self.error = None

    def alive(self):
        return self.process is not None and self.process.poll() is None

    def empty_status(self):
        from identity import IdentityStore
        store = IdentityStore(DATA / 'people.sqlite3')
        try:
            profiles = [dict(p, samples=p['sample_count']) for p in store.list_profiles()]
        finally:
            if hasattr(store, 'close'):
                store.close()
        error = self.error
        if self.process is not None and not self.alive() and self.process.returncode:
            try:
                error = json.loads((DATA / 'worker_failure.json').read_text())['error']
            except (OSError, ValueError, KeyError):
                error = '识别进程已退出，请重新开启'
        return {'active': False, 'mode': 'monitor', 'motion_enabled': False,
                'tracks': [], 'profiles': profiles, 'frame_at': None, 'camera_age': None,
                'frame_width': 640, 'frame_height': 480,
                'face_frame_width': 640, 'face_frame_height': 480, 'fps': 0,
                'enrollment': {'active': False}, 'memory': memory(), 'error': error}

    def start(self):
        with self.lock:
            if self.alive():
                return {'ok': True, 'message': '人体识别已开启'}
            if visual_busy(os.getenv('NX_PEOPLE_CAMERA', 'orbbec').lower()):
                raise ValueError('请先停止其他视觉识别、巡航录像或物体记忆，再开启人体识别')
            if memory()['system_used_gib'] > BUDGET_GIB - .70:
                raise ValueError('当前设备内存余量不足，请先停止其他视觉任务')
            (DATA / 'worker_failure.json').unlink(missing_ok=True)
            self.error = None
            with (DATA / 'worker.log').open('wb') as log:
                self.process = subprocess.Popen([sys.executable, str(ROOT / 'worker.py')],
                                                cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
            self.started_at = time.time()
            return {'ok': True, 'message': '正在加载人体与人脸识别；不会控制车轮'}

    def stop(self):
        with self.lock:
            if self.alive():
                self.process.terminate()
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=2)
            self.process = None
            self.error = None
            return {'ok': True, 'message': '识别已停止，模型内存已释放'}

    def status(self):
        with self.lock:
            if self.alive():
                try:
                    return json.loads(fetch('/api/people/status', base='http://127.0.0.1:8098', timeout=.8)[0])
                except Exception:
                    result = self.empty_status()
                    result.update(active=True, loading=True, error='正在加载识别服务')
                    return result
            return self.empty_status()

    def delete_profile(self, data):
        # Profile management also works with the models stopped.
        with self.lock:
            if self.alive():
                return json.loads(fetch('/api/people/delete-profile', data,
                                        base='http://127.0.0.1:8098', timeout=2)[0])
            from identity import IdentityStore
            store = IdentityStore(DATA / 'people.sqlite3')
            try:
                if not store.delete_profile(str(data.get('id', ''))):
                    raise ValueError('档案不存在')
            finally:
                store.close()
            return {'ok': True}


class Handler(BaseHTTPRequestHandler):
    supervisor = None

    def log_message(self, *_):
        pass

    def reply(self, value, mime='application/json', code=200):
        raw = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def proxy(self, path, body=None):
        if not self.supervisor.alive():
            return self.reply({'error': '请先开启人体识别'}, code=409)
        try:
            raw, mime = fetch(path, body, base='http://127.0.0.1:8098', timeout=2)
            self.reply(raw, mime)
        except HTTPError as exc:
            self.reply(exc.read(8192), code=exc.code)
        except Exception:
            self.reply({'error': '识别服务正在启动或暂不可用'}, code=503)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == '/api/people/status':
            return self.reply(self.supervisor.status())
        if path == '/api/people/frame.jpg':
            return self.proxy(path)
        self.reply({'error': '接口不存在'}, code=404)

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            size = int(self.headers.get('Content-Length', 0))
            if not 0 <= size <= 4096:
                raise ValueError('请求过大')
            data = json.loads(self.rfile.read(size) or '{}')
            if not isinstance(data, dict):
                raise ValueError('请求格式无效')
            if path == '/api/people/start':
                return self.reply(self.supervisor.start())
            if path == '/api/people/stop':
                return self.reply(self.supervisor.stop())
            if path == '/api/people/delete-profile':
                return self.reply(self.supervisor.delete_profile(data))
            allowed = {'select', 'unlock', 'enroll', 'supplement', 'cancel-enrollment', 'finish-enrollment', 'delete-profile', 'confirm-target'}
            if path.removeprefix('/api/people/') in allowed and path.startswith('/api/people/'):
                return self.proxy(path, data)
            return self.reply({'error': '当前版本仅静态识别，未开放运动接口'}, code=404)
        except HTTPError as exc:
            self.reply(exc.read(8192), code=exc.code)
        except ValueError as exc:
            self.reply({'error': str(exc)}, code=400)
        except Exception:
            self.reply({'error': '相机服务不可用，请稍后重试'}, code=503)


if __name__ == '__main__':
    Handler.supervisor = Supervisor()
    def stopping(signum, frame):
        Handler.supervisor.stop()
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, stopping)
    signal.signal(signal.SIGINT, stopping)
    try:
        ThreadingHTTPServer(('127.0.0.1', 8097), Handler).serve_forever()
    finally:
        Handler.supervisor.stop()
