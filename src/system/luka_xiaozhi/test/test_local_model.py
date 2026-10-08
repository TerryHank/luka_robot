import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest

from luka_xiaozhi.local_model import LocalModel


class ReleaseTests(unittest.TestCase):
    def manager(self, folder, invocation, clients=''):
        manager=LocalModel.__new__(LocalModel)
        manager.file=Path(folder)/'owner.json'
        manager.file.write_text(json.dumps({'invocation':'voice-owned'}))
        manager.lock=threading.Lock();manager.state='ready'
        manager.invocation=lambda:invocation
        calls=[]
        def command(arguments):
            calls.append(arguments)
            return SimpleNamespace(returncode=0,stdout=clients if arguments[0]=='ss' else '')
        manager.command=command
        return manager,calls

    def test_only_owned_idle_invocation_is_stopped(self):
        with tempfile.TemporaryDirectory() as folder:
            manager,calls=self.manager(folder,'voice-owned')
            manager.release()
            self.assertTrue(any(a[:4]==['sudo','-n','systemctl','stop'] for a in calls))
            self.assertFalse(manager.file.exists())

    def test_restarted_or_external_invocation_is_not_stopped(self):
        with tempfile.TemporaryDirectory() as folder:
            manager,calls=self.manager(folder,'other-owner')
            manager.release()
            self.assertEqual(calls,[])

    def test_active_shared_client_is_not_stopped(self):
        with tempfile.TemporaryDirectory() as folder:
            manager,calls=self.manager(folder,'voice-owned','ESTAB 127.0.0.1:8092 peer')
            manager.release()
            self.assertFalse(any(a[0]=='sudo' for a in calls))
            self.assertTrue(manager.file.exists())
