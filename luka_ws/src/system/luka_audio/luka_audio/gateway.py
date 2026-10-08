import fcntl
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import tempfile
import threading
import time

import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.executors import ExternalShutdownException
from std_msgs.msg import String
import sherpa_onnx

from .core import BackendError, BackendRouter, parse_result
from .frontend import AdbWake, SerialWake
from .network import NetworkMonitor
from .cue import wake_pcm
from . import music_focus


class Gateway(Node):
    def __init__(self):
        super().__init__('luka_audio_gateway')
        defaults = {
            'microphone': 'hw:CARD=XFMDPV0018,DEV=0',
            'speaker': 'plughw:CARD=Device,DEV=0',
            'frontend': 'xfm_adb', 'serial_device': '',
            'aiui_config': '/home/sunrise/.config/luka_audio/aiui.cfg',
            'model_root': '/home/sunrise/luka_data/ml_models/audio',
            'vad_model': '/home/sunrise/luka_data/ml_models/common/voice/vad/silero_vad.onnx',
            'runtime_root': '/home/sunrise/luka_data/runtime/audio',
            'dispatch_commands': False, 'backend_mode': 'auto',
            'wake_cue': True,
            'doa_calibration': '/home/sunrise/luka_ws/src/common/runtime/xfm_doa_calibration.json',
        }
        for key, value in defaults.items():
            self.declare_parameter(key, value)
        self.settings = {key: self.get_parameter(key).value for key in defaults}
        self.runtime = Path(self.settings['runtime_root'])
        self.runtime.mkdir(parents=True, exist_ok=True)
        self.lock = (self.runtime / 'owner.lock').open('w')
        fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.bin = Path(os.environ['LUKA_AUDIO_BIN'])
        self.status_pub = self.create_publisher(String, '/voice/status', 10)
        self.text_pub = self.create_publisher(String, '/voice/recognized_text', 10)
        self.wake_pub = self.create_publisher(String, '/voice/hardware_wake', 10)
        self.doa_pub = self.create_publisher(String, '/voice/doa', 10)
        self.command_pub = self.create_publisher(String, '/llm_command', 10)
        self.create_subscription(String, '/voice/tts_text', lambda msg: self.enqueue_speech(msg.data), 10)
        self.create_subscription(String, '/llm_status', self.on_llm_status, 10)
        self.create_subscription(String, '/voice/control', self.control, 10)
        self.create_subscription(String, '/xiaozhi/status', self.on_dialogue_status, 10)
        self.stop = threading.Event()
        self.cancel = threading.Event()
        self.enabled = threading.Event(); self.enabled.set()
        self.busy = threading.Event()
        self.events = queue.Queue(maxsize=1)
        self.speech = queue.Queue(maxsize=4)
        self.network = NetworkMonitor(self.stop)
        self.router = BackendRouter(self.aiui, self.rdk, self.aiui_configured, self.network.state)
        self.frontend_ready = False
        self.last_status = {'state': 'initializing'}
        self.last_completed = {}
        self.create_timer(1.0, self.repeat_status)
        config = sherpa_onnx.VadModelConfig()
        config.silero_vad.model = self.settings['vad_model']
        config.silero_vad.min_silence_duration = 0.7
        config.silero_vad.min_speech_duration = 0.2
        config.silero_vad.threshold = 0.5
        config.sample_rate = 16000
        self.vad = sherpa_onnx.VoiceActivityDetector(config, buffer_size_in_seconds=20)
        self.capture = None
        self.cue_process = None
        self.music_pause_ticket = None
        self.cue_path = self.runtime / 'wake_cue.pcm'
        self.cue_path.write_bytes(wake_pcm())
        self.threads = [threading.Thread(target=self.watch_wake, daemon=True),
                        threading.Thread(target=self.audio_loop, daemon=True)]
        for thread in self.threads:
            thread.start()

    def status(self, state, **fields):
        if self.stop.is_set() or not rclpy.ok():
            return
        self.last_status = dict(fields, state=state)
        fields.update(state=state, cloud=self.router.status, frontend=self.settings['frontend'],
                      frontend_ready=self.frontend_ready, backend_mode=self.settings['backend_mode'],
                      network_state=self.network.state(),
                      enabled=self.enabled.is_set(), busy=self.busy.is_set(),
                      dispatch_commands=self.settings['dispatch_commands'], timestamp=time.time(),
                      last_completed=self.last_completed)
        self.status_pub.publish(String(data=json.dumps(fields, ensure_ascii=False)))

    def repeat_status(self):
        status = dict(self.last_status)
        self.status(status.pop('state'), **status)

    def aiui_configured(self):
        try:
            path = Path(self.settings['aiui_config'])
            # Refuse world/group readable credentials and placeholder samples.
            if path.stat().st_mode & 0o077:
                return False
            text = path.read_text()
            values = [re.search(r'"' + key + r'"\s*:\s*"([^"]+)"', text) for key in ('appid', 'key')]
            return (self.bin / 'luka_aiui').is_file() and all(v and 'YOUR_' not in v[1] for v in values)
        except OSError:
            return False

    def native(self, command, timeout, cwd=None):
        # Kill a cancelled process before consuming its result. stdout/stderr may
        # contain SDK internals; never forward their contents to ROS or logs.
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            env = dict(os.environ)
            lib = self.bin / ('aiui_lib' if Path(command[0]).name == 'luka_aiui' else 'rdk_lib')
            env['LD_LIBRARY_PATH'] = str(lib) + ':' + env.get('LD_LIBRARY_PATH', '')
            process = subprocess.Popen(command, stdout=stdout, stderr=stderr, cwd=cwd, env=env)
            deadline = time.monotonic() + timeout
            while process.poll() is None:
                if self.stop.is_set() or self.cancel.is_set() or time.monotonic() > deadline:
                    process.kill(); process.wait()
                    if self.cancel.is_set() or self.stop.is_set():
                        raise InterruptedError('cancelled')
                    raise TimeoutError('speech backend timed out')
                time.sleep(0.05)
            stdout.seek(0)
            output = stdout.read().decode('utf8', errors='replace')
            if process.returncode:
                try:
                    parse_result(output)
                except BackendError:
                    raise
                except RuntimeError:
                    pass
                raise RuntimeError('speech backend failed: exit ' + str(process.returncode))
            return parse_result(output)

    def aiui(self, operation, payload):
        with tempfile.TemporaryDirectory(dir=self.runtime) as folder:
            folder = Path(folder)
            (folder / 'AIUI').mkdir()
            input_path, output_path = folder / 'input', folder / 'output.pcm'
            input_path.write_bytes(payload if operation == 'asr' else payload.encode('utf8'))
            result = self.native([str(self.bin / 'luka_aiui'), operation, self.settings['aiui_config'],
                                  str(input_path), str(output_path)], 32, cwd=folder)
            if operation == 'tts':
                result['pcm'] = output_path.read_bytes()
            return result

    def rdk(self, operation, payload):
        root = Path(self.settings['model_root'])
        with tempfile.TemporaryDirectory(dir=self.runtime) as folder:
            input_path, output_path = Path(folder) / 'input', Path(folder) / 'output.pcm'
            input_path.write_bytes(payload if operation == 'asr' else payload.encode('utf8'))
            if operation == 'asr':
                command = [str(self.bin / 'luka_rdk_asr'), str(root / 'rdk_sensevoice/model.gguf'), str(input_path)]
            else:
                command = [str(self.bin / 'luka_rdk_tts'), str(root / 'rdk_tts/tts_model'),
                           str(input_path), str(output_path)]
            result = self.native(command, 60)
            if operation == 'tts':
                result['pcm'] = output_path.read_bytes()
            return result

    def watch_wake(self):
        reader = None
        while not self.stop.is_set():
            try:
                if reader is None:
                    reader = (AdbWake() if self.settings['frontend'] == 'xfm_adb'
                              else SerialWake(self.settings['serial_device']))
                event = reader.poll()
                self.frontend_ready = True
                if event:
                    event['angle_deg'] = float(event['angle']) % 360
                    try:
                        front = float(json.loads(Path(self.settings['doa_calibration']).read_text())['front_angle_deg'])
                        event.update(front_angle_deg=front, relative_angle_deg=(event['angle_deg'] - front) % 360,
                                     calibrated=True)
                    except (OSError, ValueError, KeyError, TypeError):
                        event['calibrated'] = False
                    destination = self.runtime / 'xfm_doa.json'
                    temporary = destination.with_suffix('.tmp')
                    temporary.write_text(json.dumps(event, ensure_ascii=False))
                    temporary.replace(destination)
                    self.doa_pub.publish(String(data=json.dumps(event, ensure_ascii=False)))
                    self.wake_pub.publish(String(data=json.dumps(event, ensure_ascii=False)))
                    if self.enabled.is_set() and not self.busy.is_set():
                        try:
                            self.events.put_nowait(event)
                        except queue.Full:
                            pass
            except Exception as exc:
                self.frontend_ready = False
                if reader is not None and hasattr(reader, 'close'):
                    reader.close()
                reader = None
                self.status('frontend_unavailable', error=type(exc).__name__)
                self.stop.wait(2)
            self.stop.wait(0.2)
        if reader is not None and hasattr(reader, 'close'):
            reader.close()

    def enqueue_speech(self, text):
        if text.strip() and self.enabled.is_set():
            try:
                self.speech.put_nowait(text.strip()[:150])
            except queue.Full:
                self.status('speech_queue_full')

    def on_llm_status(self, msg):
        if msg.data.startswith('speech:'):
            self.enqueue_speech(msg.data.partition(':')[2])
        elif msg.data.startswith('answer['):
            self.enqueue_speech(msg.data.partition(']: ')[2])

    def control(self, msg):
        if msg.data.strip() in ('stop', 'sleep', 'disable', 'cancel'):
            self.cancel.set()
            if msg.data.strip() != 'cancel':
                self.enabled.clear()
        elif msg.data.strip() in ('start', 'enable'):
            self.cancel.clear(); self.enabled.set()

    def on_dialogue_status(self, msg):
        try:
            status = json.loads(msg.data).get('state')
        except ValueError:
            return
        if status in ('dialogue_unavailable', 'speech_backend_unavailable', 'speech_backend_failed', 'dialogue_busy', 'cancelled', 'task_failed', 'task_interrupted'):
            music_focus.resume(self.music_pause_ticket); self.music_pause_ticket = None

    def play(self, result):
        pcm = result['pcm']
        if not pcm or len(pcm) % 2:
            raise RuntimeError('invalid synthesized PCM')
        path = self.runtime / 'playback.pcm'
        path.write_bytes(pcm)
        previous_music_volume = music_focus.duck()
        try:
            self.native_playback = subprocess.Popen(['aplay', '-q', '-D', self.settings['speaker'],
                '-t', 'raw', '-f', 'S16_LE', '-r', str(result['rate']), '-c', str(result['channels']), str(path)])
            while self.native_playback.poll() is None:
                if self.cancel.is_set() or self.stop.is_set():
                    self.native_playback.terminate()
                    self.native_playback.wait(timeout=2)
                    raise InterruptedError('cancelled')
                time.sleep(0.05)
            if self.native_playback.returncode:
                raise RuntimeError('speaker playback failed')
        finally:
            music_focus.restore(previous_music_volume)
            path.unlink(missing_ok=True)

    def transact(self, operation, payload):
        try:
            return self.router.run(operation, payload)
        except InterruptedError:
            return None
        except (RuntimeError, TimeoutError, OSError) as exc:
            fields = dict(operation=operation, error=type(exc).__name__)
            if isinstance(exc, BackendError):
                fields.update(error_code=exc.error_code, error_scope=exc.error_scope, timed_out=exc.timed_out)
            self.status('backend_unavailable', **fields)
            return None

    def start_capture(self):
        self.capture = subprocess.Popen(['arecord', '-q', '-D', self.settings['microphone'],
            '-t', 'raw', '-f', 'S16_LE', '-r', '16000', '-c', '1'], stdout=subprocess.PIPE)

    def confirm_wake(self):
        ticket = music_focus.pause()
        if ticket is not None: self.music_pause_ticket = ticket
        if self.settings['wake_cue']:
            self.cue_process = subprocess.Popen(['aplay','-q','-D',self.settings['speaker'],
                '-t','raw','-f','S16_LE','-r','16000','-c','1',str(self.cue_path)])

    def stop_capture(self):
        if self.capture and self.capture.poll() is None:
            self.capture.terminate(); self.capture.wait(timeout=2)

    def audio_loop(self):
        session = None
        heard_speech = False
        try:
            self.start_capture()
            self.status('waiting_hardware_wake')
            while not self.stop.is_set():
                data = self.capture.stdout.read(1024)
                if len(data) != 1024:
                    if self.stop.is_set() or not rclpy.ok():
                        break
                    raise RuntimeError('microphone capture ended')
                if self.cancel.is_set():
                    session = None; self.busy.clear(); self.vad.reset()
                    self.status('waiting_hardware_wake' if self.enabled.is_set() else 'disabled')
                    while not self.events.empty(): self.events.get_nowait()
                    while not self.speech.empty(): self.speech.get_nowait()
                    if self.enabled.is_set(): self.cancel.clear()
                    music_focus.resume(self.music_pause_ticket); self.music_pause_ticket = None
                    continue
                if not self.enabled.is_set():
                    continue
                if session is None and not self.speech.empty():
                    self.busy.set()
                    text = self.speech.get_nowait()
                    self.stop_capture()
                    response = self.transact('tts', text)
                    if response:
                        backend, result = response
                        self.status('speaking', backend=backend)
                        try:
                            self.play(result)
                            self.last_completed = dict(operation='tts', backend=backend,
                                                       timestamp=time.time(), samples=len(result['pcm']) // 2)
                        except InterruptedError:
                            pass
                        except (RuntimeError, OSError) as exc:
                            self.status('playback_failed', error=type(exc).__name__)
                    # Ignore board wakes and drain buffered microphone audio
                    # until playback echo has ended; full-duplex AEC is unverified.
                    time.sleep(0.4)
                    self.start_capture()
                    self.busy.clear(); self.status('waiting_hardware_wake')
                    music_focus.resume(self.music_pause_ticket); self.music_pause_ticket = None
                    continue
                if session is None and not self.events.empty():
                    event = self.events.get_nowait()
                    if time.time() - event['observed_at'] > 1.5:
                        continue
                    self.busy.set(); self.vad.reset()
                    session = time.monotonic(); heard_speech = False
                    self.status('listening', angle=event.get('angle'))
                    self.confirm_wake()
                if session is None:
                    continue
                samples = np.frombuffer(data, dtype='<i2').astype(np.float32) / 32768
                self.vad.accept_waveform(samples)
                heard_speech = heard_speech or self.vad.is_speech_detected()
                if not self.vad.empty():
                    pcm = (np.clip(self.vad.front.samples, -1, 1) * 32767).astype('<i2').tobytes()
                    self.vad.pop()
                    self.stop_capture()
                    response = self.transact('asr', pcm)
                    if response and not self.cancel.is_set() and self.enabled.is_set():
                        backend, result = response
                        text = result['text'].strip()
                        self.status('recognized', backend=backend)
                        if text:
                            self.text_pub.publish(String(data=text))
                            if self.settings['dispatch_commands']:
                                self.command_pub.publish(String(data=text))
                            self.last_completed = dict(operation='asr', backend=backend, timestamp=time.time())
                    self.start_capture()
                    session = None; self.busy.clear(); self.vad.reset()
                    if not response or response[1].get('text', '').strip() in ('', '露卡', '卢卡'):
                        music_focus.resume(self.music_pause_ticket); self.music_pause_ticket = None
                elif time.monotonic() - session > (12 if heard_speech else 6):
                    self.status('utterance_timeout')
                    session = None; self.busy.clear(); self.vad.reset()
                    music_focus.resume(self.music_pause_ticket); self.music_pause_ticket = None
        except Exception as exc:
            self.status('audio_stopped', error=type(exc).__name__)
            self.stop.set()
        finally:
            if self.capture and self.capture.poll() is None:
                self.capture.terminate(); self.capture.wait(timeout=2)

    def close(self):
        self.stop.set(); self.cancel.set()
        if self.cue_process and self.cue_process.poll() is None:
            self.cue_process.terminate(); self.cue_process.wait(timeout=2)
        if self.capture and self.capture.poll() is None:
            self.capture.terminate()
        for thread in self.threads:
            thread.join(timeout=5)
        self.network.thread.join(timeout=4)


def main():
    rclpy.init()
    node = Gateway()
    try:
        while rclpy.ok() and not node.stop.is_set():
            rclpy.spin_once(node, timeout_sec=0.2)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        failed = node.stop.is_set() and rclpy.ok()
        node.close(); node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        if failed:
            raise SystemExit(1)


if __name__ == '__main__':
    main()
