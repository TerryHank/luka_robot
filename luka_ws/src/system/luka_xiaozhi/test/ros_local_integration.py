"""Real local ASR -> ROS client -> real local LLM -> real local TTS.

No microphone, speaker or robot actuator is opened. Run in isolated ROS domain.
"""
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import threading

import numpy as np
import rclpy
from rclpy.executors import SingleThreadedExecutor
from std_msgs.msg import String
from luka_xiaozhi.ros_client import Client
from luka_audio.network import NetworkMonitor


def native(command, lib):
    env = dict(os.environ); env['LD_LIBRARY_PATH'] = str(lib) + ':' + env.get('LD_LIBRARY_PATH', '')
    result = subprocess.run(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    assert result.returncode == 0, 'native speech backend failed'
    for line in reversed(result.stdout.decode('utf8', errors='replace').splitlines()):
        try: value = json.loads(line)
        except ValueError: continue
        if value.get('ok'): return value
    raise AssertionError('no successful speech result')


def main():
    root = Path('/home/sunrise/luka_data/runtime/xiaozhi/acceptance'); root.mkdir(parents=True, exist_ok=True)
    control = json.loads((root / 'network_control.json').read_text())
    assert control['control_ok'] and time.time() - control['timestamp'] < 300
    blocked = False
    try:
        connection = socket.create_connection((control['public_ip'], 443), timeout=1)
        connection.close()
    except (PermissionError, TimeoutError):
        blocked = True
    assert blocked, 'run this test under per-process public-network denial'
    stop_network=threading.Event()
    network=NetworkMonitor(stop_network)
    deadline=time.monotonic()+15
    while network.state()!='offline' and time.monotonic()<deadline: time.sleep(.2)
    assert network.state()=='offline','offline must be confirmed by the actual network monitor'
    audio = Path('/home/sunrise/luka_ws/install/luka_audio/lib/luka_audio')
    models = Path('/home/sunrise/luka_data/ml_models/audio')
    recording = Path('/home/sunrise/luka_data/runtime/audio/acceptance/tts.pcm')
    with tempfile.TemporaryDirectory(dir=root) as directory:
        directory = Path(directory)
        cfg = directory / 'config.json'
        cfg.write_text(json.dumps({'dialogue_mode': 'auto', 'local_llm': {
            'url': 'http://127.0.0.1:8092/v1/chat/completions', 'model': 'qwen2.5-1.5b-instruct-bpu', 'max_tokens': 64, 'timeout': 60}}))
        cfg.chmod(0o600)
        rclpy.init(args=['--ros-args', '-p', 'config_file:=' + str(cfg), '-p', 'runtime_root:=' + str(directory / 'runtime')])
        client = Client()
        def forbidden(*args): raise AssertionError('AIUI called in local mode')
        client.dialogue.online.ask = forbidden
        observer = rclpy.create_node('xiaozhi_local_acceptance')
        results, commands, chunks = [], [], []
        observer.create_subscription(String, '/xiaozhi/answer', lambda msg: results.append(msg.data), 10)
        observer.create_subscription(String, '/voice/tts_text', lambda msg: chunks.append(msg.data), 10)
        observer.create_subscription(String, '/llm_command', lambda msg: commands.append(msg.data), 10)
        status = observer.create_publisher(String, '/voice/status', 10)
        text_pub = observer.create_publisher(String, '/voice/recognized_text', 10)
        executor = SingleThreadedExecutor(); executor.add_node(client); executor.add_node(observer)
        last_completed = {}; timings = []
        try:
            asr = native([str(audio / 'luka_rdk_asr'), str(models / 'rdk_sensevoice/model.gguf'), str(recording)], audio / 'rdk_lib')
            assert '你好' in asr['text'] and '天气' in asr['text'], asr
            inputs = [asr['text'], '我叫小明，请记住我的名字。', '我叫什么名字？']
            for number, question in enumerate(inputs):
                deadline = time.monotonic() + 75; sent = False; synthesized = 0
                started = time.monotonic()
                answer_count = len(results)
                while time.monotonic() < deadline:
                    state = {'state': 'waiting_hardware_wake', 'frontend_ready': True, 'backend_mode': 'rdk',
                             'network_state': network.state(),
                             'last_completed': last_completed, 'timestamp': time.time()}
                    status.publish(String(data=json.dumps(state)))
                    executor.spin_once(timeout_sec=.1)
                    if not sent and client.audio:
                        text_pub.publish(String(data=question)); sent = True
                    while chunks:
                        sentence = chunks.pop(0)
                        source, output = directory / 'text.txt', directory / 'output.pcm'
                        source.write_text(sentence)
                        value = native([str(audio / 'luka_rdk_tts'), str(models / 'rdk_tts/tts_model'),
                                        str(source), str(output)], audio / 'rdk_lib')
                        samples = np.fromfile(output, dtype='<i2')
                        assert samples.size > 0 and np.mean(np.abs(samples.astype(float)) >= 32767) < .01
                        last_completed = {'operation': 'tts', 'timestamp': time.time()}
                        synthesized += 1
                    if len(results) > answer_count and not client.busy and synthesized:
                        timings.append(round(time.monotonic() - started, 2)); break
                else:
                    raise AssertionError('local voice chain timed out')
            assert '小明' in results[-1], results
            assert not commands, commands
            result = {'pass': True, 'public_network_denied': blocked, 'real_local_asr': asr['text'],
                      'answers': results, 'local_chain_seconds': timings, 'llm_command_count': len(commands),
                      'hardware_recording_and_playback': 'not part of this test'}
            (root / 'offline_chain.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
            print(json.dumps(result, ensure_ascii=False))
        finally:
            stop_network.set(); network.thread.join(timeout=4)
            client.close(); executor.shutdown(); client.destroy_node(); observer.destroy_node()
            if rclpy.ok(): rclpy.shutdown()


if __name__ == '__main__': main()
