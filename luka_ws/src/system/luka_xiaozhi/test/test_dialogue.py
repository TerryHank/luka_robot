from collections import deque
import json
from pathlib import Path
import runpy
import socket
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from luka_xiaozhi.dialogue import Dialogue, speech_chunks, spoken_text
from luka_xiaozhi.moss_client import MossDialogue


class Connection:
    def __init__(self, mode='answer', cancel=None):
        self.mode, self.cancel = mode, cancel
        self.sent, self.replies = [], deque()
        self.closed = False

    def settimeout(self, value): pass
    def connect(self, path): self.path = path
    def close(self): self.closed = True

    def sendall(self, raw):
        value = json.loads(raw); self.sent.append(value)
        if value['type'] == 'create_task':
            self.task = value['task_id']
            if self.mode == 'local': self.replies.append({'type': 'ensure_local', 'request_id': 'ready'})
            elif self.mode == 'error': self.replies.append({'type': 'error', 'task_id': self.task, 'error': 'cloud_error'})
            elif self.mode == 'late': self.cancel.set(); self.replies.append({'type': 'answer', 'task_id': self.task, 'text': 'late', 'provider': 'aiui'})
            else: self.replies.append({'type': 'answer', 'task_id': self.task, 'text': '回复', 'provider': 'aiui'})
        if value['type'] == 'local_ready':
            self.replies.append({'type': 'answer', 'task_id': self.task, 'text': '本地回复', 'provider': 'local_qwen'})
        if value['type'] == 'cancel_task': self.replies.append({'type': 'cancelled', 'task_id': self.task})

    def recv(self, size):
        if not self.replies: raise socket.timeout()
        return (json.dumps(self.replies.popleft(), ensure_ascii=False) + '\n').encode()


class DialogueTests(unittest.TestCase):
    def client(self, connection, local_ready=lambda cancel: None):
        client = MossDialogue({}, lambda: 'online', local_ready)
        client.socket = connection
        return client

    def test_task_uses_correlated_id_and_preserves_session(self):
        connection = Connection(); client = self.client(connection)
        self.assertEqual(client.ask('任意表达', threading.Event()), ('aiui', ['回复']))
        self.assertEqual(client.ask('接着上一句', threading.Event()), ('aiui', ['回复']))
        tasks = [item for item in connection.sent if item['type'] == 'create_task']
        self.assertNotEqual(tasks[0]['task_id'], tasks[1]['task_id'])
        self.assertEqual(tasks[0]['session_id'], tasks[1]['session_id'])

    def test_network_updates_are_sent_without_choosing_a_second_backend(self):
        connection = Connection(); client = self.client(connection)
        client.update_network()
        self.assertEqual(connection.sent[-1]['state'], 'online')
        self.assertEqual(connection.sent[-1]['type'], 'network')

    def test_local_model_preparation_is_requested_by_moss(self):
        calls = []; connection = Connection('local')
        client = self.client(connection, lambda cancel: calls.append(True))
        self.assertEqual(client.ask('查询状态', threading.Event())[0], 'local_qwen')
        self.assertEqual(calls, [True])
        self.assertTrue(any(item['type'] == 'local_ready' and item['ok'] for item in connection.sent))

    def test_cloud_error_is_reported_and_never_retried_locally(self):
        connection = Connection('error')
        client = self.client(connection, lambda cancel: self.fail('fallback called'))
        with self.assertRaises(RuntimeError): client.ask('你好', threading.Event())
        self.assertEqual(client.last_error_code, 'cloud_error')

    def test_pre_cancelled_request_is_not_sent(self):
        connection = Connection(); client = self.client(connection)
        cancel = threading.Event(); cancel.set()
        with self.assertRaises(InterruptedError): client.ask('请求', cancel)
        self.assertEqual(connection.sent, [])

    def test_cancel_drops_late_answer_and_cancels_same_task(self):
        cancel = threading.Event(); connection = Connection('late', cancel)
        client = self.client(connection)
        with self.assertRaises(InterruptedError): client.ask('请求', cancel)
        self.assertTrue(any(item['type'] == 'cancel_task' and item['task_id'] == connection.task for item in connection.sent))

    def test_close_releases_transport(self):
        connection = Connection(); client = self.client(connection)
        client.close(); self.assertTrue(connection.closed); self.assertIsNone(client.socket)

    def test_compatibility_constructor_delegates_to_single_owner(self):
        with patch('luka_xiaozhi.moss_client.MossDialogue') as proxy:
            proxy.return_value.ask.return_value = ('moss', ['reply'])
            client = Dialogue({})
            self.assertEqual(client.ask('hello', threading.Event()), ('moss', ['reply']))

    def test_reasoning_not_spoken(self):
        self.assertEqual(spoken_text('<think>推理</think>你好。'), '你好。')
        with self.assertRaises(RuntimeError): spoken_text('<think>未结束的推理')

    def test_control_json_not_spoken(self):
        with self.assertRaises(RuntimeError): spoken_text('{"tool":"navigate"}')

    def test_chunking_keeps_every_character(self):
        text = '这是测试。' * 100
        parts = speech_chunks(text)
        self.assertEqual(''.join(parts), text)
        self.assertTrue(all(len(part) <= 120 for part in parts))

    def test_fork_ros_mode_bypasses_original_audio(self):
        entry = Path(__file__).parents[1] / 'xiaozhi-in-rdk.py'
        called = []
        for arguments in ([], ['--ros-speech']):
            with patch.object(sys, 'argv', [str(entry)] + arguments), patch.dict(sys.modules,
                {'luka_xiaozhi.ros_client': SimpleNamespace(main=lambda: called.append(True))}):
                with self.assertRaises(SystemExit) as exited: runpy.run_path(str(entry), run_name='__main__')
                self.assertEqual(exited.exception.code, 0)
        self.assertEqual(called, [True, True])
