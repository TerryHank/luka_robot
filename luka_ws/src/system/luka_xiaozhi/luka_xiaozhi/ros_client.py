import fcntl
import json
from pathlib import Path
import queue
import threading
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from .dialogue import speech_chunks
from .moss_client import MossDialogue
from .local_model import LocalModel


class Client(Node):
    def __init__(self):
        super().__init__('luka_xiaozhi')
        self.declare_parameter('config_file', '/home/sunrise/.config/luka_xiaozhi/config.json')
        self.declare_parameter('runtime_root', '/home/sunrise/luka_data/runtime/xiaozhi')
        path = Path(self.get_parameter('config_file').value)
        if path.exists() and path.stat().st_mode & 0o077:
            raise RuntimeError('private XiaoZhi config must have mode 600')
        defaults = {'dialogue_mode': 'auto', 'local_llm': {'url': 'http://127.0.0.1:8092/v1/chat/completions',
                    'model': 'qwen2.5-1.5b-instruct-bpu', 'max_tokens': 64, 'timeout': 60}}
        self.config = json.loads(path.read_text()) if path.exists() else defaults
        runtime = Path(self.get_parameter('runtime_root').value)
        runtime.mkdir(parents=True, exist_ok=True)
        self.owner = (runtime / 'owner.lock').open('w')
        fcntl.flock(self.owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.status_pub = self.create_publisher(String, '/xiaozhi/status', 10)
        self.latest_status = ('initializing', {})
        self.answer_pub = self.create_publisher(String, '/xiaozhi/answer', 10)
        self.compat_answer_pub = self.create_publisher(String, '/llm_status', 10)
        self.tts_pub = self.create_publisher(String, '/voice/tts_text', 10)
        self.create_subscription(String, '/voice/recognized_text', self.recognized, 10)
        self.create_subscription(String, '/llm_command', lambda msg: self.recognized(msg, from_voice=False), 10)
        self.create_subscription(String, '/voice/status', self.audio_status, 10)
        self.create_subscription(String, '/voice/hardware_wake', self.wake_status, 10)
        self.create_subscription(String, '/voice/control', self.control, 10)
        self.stop = threading.Event()
        self.guard = threading.Lock()
        self.cancel = threading.Event()
        self.requests = queue.Queue(maxsize=1)
        self.busy = False
        self.thinking = False
        self.chunks = []
        self.playing_at = None
        self.audio = None
        self.audio_at = 0
        self.enabled = True
        local=self.config.get('local_llm',{})
        memory_min=768 if local.get('model')=='qwen2.5-1.5b-instruct-bpu' else 3500
        self.local_model = LocalModel(runtime,self.stop,self.network_state,lambda:self.busy,memory_min)
        self.dialogue = MossDialogue(self.config, self.network_state, self.local_model.ensure, self.status)
        self.worker = threading.Thread(target=self.process, daemon=True)
        self.worker.start()
        self.create_timer(.1, self.play_next)
        self.create_timer(1.0, self.repeat_status)
        self.status('waiting_hardware_wake')

    def status(self, state, **extra):
        self.latest_status = (state, dict(extra))
        if rclpy.ok():
            self.status_pub.publish(String(data=json.dumps(dict(state=state, timestamp=time.time(),
                online_state=self.dialogue.cloud_state, online_error_code=self.dialogue.last_error_code,
                enabled=self.enabled, busy=self.busy, local_model_state=self.local_model.state,
                dialogue_mode=self.config.get('dialogue_mode', 'auto'), **extra), ensure_ascii=False)))

    def repeat_status(self):
        self.dialogue.update_network()
        state, extra = self.latest_status
        self.status(state, **extra)

    def network_state(self):
        if not self.audio or time.monotonic() - self.audio_at > 3:
            return 'unknown'
        return self.audio.get('network_state', 'unknown')

    def wake_status(self, msg):
        # Hardware KWS already gates the audio gateway. This client never opens
        # a microphone or treats the wake word as a keyboard recording trigger.
        try:
            event = json.loads(msg.data)
            if 0 <= time.time() - float(event['observed_at']) < 2 and not self.busy:
                self.status('hardware_wake', angle=event.get('angle_deg'))
        except (ValueError, KeyError, TypeError):
            pass

    def audio_status(self, msg):
        try:
            self.audio = json.loads(msg.data)
            self.audio_at = time.monotonic()
        except ValueError:
            pass

    def recognized(self, msg, from_voice=True):
        text = msg.data.strip()
        # Audio gateway can include the wake word if a pre-roll is used later.
        for prefix in ('露卡', '卢卡'):
            if text.startswith(prefix):
                text = text[len(prefix):].lstrip('，,。:： ')
                break
        if not text or len(text) > 400 or not self.enabled:
            return
        with self.guard:
            if self.busy:
                self.status('dialogue_busy')
                return
            if not self.audio or time.monotonic() - self.audio_at > 3 or from_voice and not self.audio.get('frontend_ready'):
                self.status('speech_backend_unavailable')
                return
            self.busy = True
            self.thinking = True
            self.cancel = threading.Event()
            self.requests.put_nowait((text, self.cancel))

    def control(self, msg):
        value = msg.data.strip()
        if value in ('cancel', 'stop', 'sleep', 'disable'):
            with self.guard:
                self.cancel.set(); self.chunks.clear(); self.playing_at = None
                if value != 'cancel':
                    self.enabled = False
            self.status('cancelled')
        elif value in ('start', 'enable'):
            self.enabled = True

    def process(self):
        while not self.stop.is_set():
            try:
                text, cancel = self.requests.get(timeout=.2)
            except queue.Empty:
                continue
            try:
                self.status('thinking')
                backend, answer = self.dialogue.ask(text, cancel)
                with self.guard:
                    if cancel.is_set() or self.stop.is_set():
                        continue
                    self.chunks = [part for sentence in answer for part in speech_chunks(sentence)]
                    self.answer_pub.publish(String(data=''.join(answer)))
                    self.compat_answer_pub.publish(String(data=''.join(answer)))
                    self.status('answer_ready', dialogue_backend=backend)
            except InterruptedError:
                self.status('cancelled')
            except Exception as exc:
                # Do not log broker credentials, HTTP bodies or private text.
                self.status('dialogue_unavailable', error=type(exc).__name__)
            finally:
                with self.guard:
                    self.thinking = False
                    if not self.chunks and self.playing_at is None:
                        self.busy = False

    def play_next(self):
        with self.guard:
            if self.playing_at is not None:
                completed = (self.audio or {}).get('last_completed', {})
                if completed.get('operation') == 'tts' and completed.get('timestamp', 0) >= self.playing_at:
                    self.playing_at = None
                elif (self.audio or {}).get('state') in ('audio_stopped', 'backend_unavailable', 'playback_failed') or time.time() - self.playing_at > 65:
                    self.chunks.clear(); self.playing_at = None; self.busy = False
                    self.status('speech_backend_failed')
                else:
                    return
            if self.chunks and self.enabled and not self.cancel.is_set():
                if not self.audio or time.monotonic() - self.audio_at > 3:
                    return
                self.playing_at = time.time()
                self.tts_pub.publish(String(data=self.chunks.pop(0)))
                self.status('speaking')
            elif self.busy and not self.thinking and self.requests.empty() and self.playing_at is None:
                self.busy = False
                self.status('waiting_hardware_wake')

    def close(self):
        self.stop.set(); self.cancel.set()
        self.dialogue.close()
        self.worker.join(timeout=30)
        self.local_model.close()


def main():
    rclpy.init()
    node = Client()
    try:
        rclpy.spin(node)
    finally:
        node.close(); node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
