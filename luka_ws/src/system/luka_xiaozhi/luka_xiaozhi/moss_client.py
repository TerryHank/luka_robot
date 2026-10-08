"""Existing ROS speech client delegates tasks to the single local Moss owner."""
import json
import socket
import threading
import time
import uuid


class MossDialogue:
    def __init__(self, config, network, local_ready, status=lambda *args, **kwargs: None):
        self.path = config.get('moss_socket', '/home/sunrise/luka_data/runtime/agent/moss.sock')
        self.network, self.local_ready, self.status = network, local_ready, status
        self.session = uuid.uuid4().hex
        self.socket = None
        self.writer = threading.Lock()
        self.buffer = b''
        self.cloud_state = 'unverified'
        self.last_error_code = None

    def send(self, value):
        with self.writer:
            if self.socket is not None:
                self.socket.sendall((json.dumps(value, ensure_ascii=False) + '\n').encode('utf8'))

    def update_network(self):
        if self.socket is not None:
            try: self.send(dict(type='network', state=self.network(), timestamp=time.time()))
            except OSError: pass

    def connect(self):
        if self.socket is None:
            connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            connection.settimeout(3)
            connection.connect(self.path)
            connection.settimeout(.25)
            self.socket = connection
            self.send(dict(type='hello'))
        self.update_network()

    def ask(self, text, cancel):
        if cancel.is_set(): raise InterruptedError('cancelled')
        self.connect()
        task_id = uuid.uuid4().hex
        self.send(dict(type='create_task', task_id=task_id, session_id=self.session, text=text))
        deadline = time.monotonic() + 300
        cancelling = False
        try:
            while time.monotonic() < deadline:
                if cancel.is_set() and not cancelling:
                    self.send(dict(type='cancel_task', task_id=task_id))
                    cancelling = True; deadline = time.monotonic() + 12
                try:
                    data = self.socket.recv(65536)
                    if not data: raise RuntimeError('Moss connection ended')
                    self.buffer += data
                except socket.timeout:
                    continue
                if len(self.buffer) > 262144: raise RuntimeError('Moss response too large')
                while b'\n' in self.buffer:
                    raw, self.buffer = self.buffer.split(b'\n', 1)
                    event = json.loads(raw)
                    if event.get('type') == 'ensure_local':
                        try:
                            self.local_ready(cancel)
                            self.send(dict(type='local_ready', request_id=event['request_id'], ok=True))
                        except Exception:
                            self.send(dict(type='local_ready', request_id=event['request_id'], ok=False))
                        continue
                    if event.get('task_id') != task_id: continue
                    self.status('task_' + event.get('phase', 'unknown'), task_id=task_id,
                                execution_mode=event.get('execution_mode'), tool=event.get('tool'),
                                operation_state=event.get('operation_state'))
                    if event.get('type') == 'answer':
                        if cancelling: raise InterruptedError('cancelled')
                        self.cloud_state = 'healthy' if event.get('provider') == 'aiui' else 'offline'
                        return event.get('provider', 'moss'), [event['text']]
                    if event.get('type') == 'cancelled': raise InterruptedError('cancelled')
                    if event.get('type') == 'error':
                        self.cloud_state = 'unavailable'; self.last_error_code = event.get('error')
                        raise RuntimeError('Moss task failed: ' + str(self.last_error_code))
            if cancelling: raise InterruptedError('cancelled')
            self.send(dict(type='cancel_task', task_id=task_id))
            raise TimeoutError('Moss task timed out')
        except (OSError, ValueError):
            self.close()
            raise

    def close(self):
        with self.writer:
            if self.socket is not None:
                self.socket.close(); self.socket = None
        self.buffer = b''
