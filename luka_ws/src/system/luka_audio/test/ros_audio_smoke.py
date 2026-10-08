"""Recorded PCM and simulated hardware event; no speaker or robot commands."""
import json
import os
from pathlib import Path
import tempfile
import time
import threading

import rclpy
from rclpy.executors import SingleThreadedExecutor
from std_msgs.msg import String
import luka_audio.gateway as gateway


class RecordedWake:
    def __init__(self):
        self.deadline = time.monotonic() + 0.5
        self.sent = False

    def poll(self):
        if not self.sent and time.monotonic() > self.deadline:
            self.sent = True
            return {'observed_at': time.time(), 'angle': 45, 'source': 'simulated_hardware_event'}
        return None


def main():
    root = Path('/home/sunrise/luka_data/runtime/audio/acceptance')
    import numpy as np
    pcm = np.fromfile(root / 'tts.pcm', dtype='<i2')
    assert np.mean(np.abs(pcm.astype(float)) >= 32767) < .01, 'TTS output clipped'
    assert 50 < np.sqrt(np.mean(pcm.astype(float) ** 2)) < 15000, 'TTS level invalid'
    with tempfile.TemporaryDirectory(dir=root) as folder:
        folder = Path(folder)
        fake = folder / 'arecord'
        fake.write_text('''#!/usr/bin/env python3
import sys,time
from pathlib import Path
data = bytes(32000) + Path('/home/sunrise/luka_data/runtime/audio/acceptance/tts.pcm').read_bytes() + bytes(64000)
for i in range(0,len(data),1024):
 sys.stdout.buffer.write(data[i:i+1024].ljust(1024,b'\\0'));sys.stdout.buffer.flush();time.sleep(.032)
while True:
 sys.stdout.buffer.write(bytes(1024));sys.stdout.buffer.flush();time.sleep(.032)
''')
        fake.chmod(0o755)
        os.environ['PATH'] = str(folder) + ':' + os.environ['PATH']
        gateway.AdbWake = RecordedWake
        rclpy.init(args=['--ros-args', '-p', 'runtime_root:=' + str(folder / 'runtime')])
        node = gateway.Gateway()
        # Exercise actual SDK failure -> local fallback with the same PCM.
        node.router.configured = lambda: True
        observer = rclpy.create_node('luka_audio_acceptance')
        received, commands, statuses = [], [], []
        observer.create_subscription(String, '/voice/recognized_text', lambda m: received.append(m.data), 10)
        observer.create_subscription(String, '/llm_command', lambda m: commands.append(m.data), 10)
        observer.create_subscription(String, '/voice/status', lambda m: statuses.append(json.loads(m.data)), 10)
        executor = SingleThreadedExecutor()
        executor.add_node(node); executor.add_node(observer)
        deadline = time.monotonic() + 20
        try:
            while time.monotonic() < deadline and not received and not node.stop.is_set():
                executor.spin_once(timeout_sec=.1)
            assert len(received) == 1, ('expected one utterance', received, statuses)
            assert '你好' in received[0] and '天气' in received[0], received
            assert not commands, commands
            assert any(s.get('backend') == 'rdk' and s['state'] == 'recognized' for s in statuses), statuses
            print(json.dumps({'pass': True, 'recognized': received, 'llm_command_count': len(commands),
                              'cloud_fallback': node.router.status}, ensure_ascii=False))
            # A cancellation must abort a running native process and never retry.
            node.cancel.clear()
            timer = threading.Timer(.2, node.cancel.set); timer.start()
            started = time.monotonic()
            try:
                node.native(['/usr/bin/sleep', '10'], 15)
                raise AssertionError('cancelled process succeeded')
            except InterruptedError:
                assert time.monotonic() - started < 2
                print('PASS native cancellation')
            finally:
                timer.join()
        finally:
            node.close(); executor.shutdown(); observer.destroy_node(); node.destroy_node(); rclpy.shutdown()


if __name__ == '__main__':
    main()
