import unittest
from luka_audio.core import BackendError, BackendRouter, SerialFrames, WakeEvents, parse_result, serial_frame


class AudioTests(unittest.TestCase):
    def test_partial_and_checksum(self):
        parser = SerialFrames()
        packet = serial_frame(4, 65535, b'{"type":"aiui_event"}')
        self.assertEqual(parser.feed(packet[:4]), [])
        self.assertEqual(parser.feed(packet[4:]), [(4, 65535, packet[7:-1])])
        bad = packet[:-1] + bytes([packet[-1] ^ 1])
        self.assertEqual(parser.feed(bad + packet), [(4, 65535, packet[7:-1])])

    def test_oversized_resynchronises(self):
        parser = SerialFrames()
        self.assertEqual(parser.feed(b'\xa5\x01\x04\xff\xff\0\0' + serial_frame(1, 7, b'x')),
                         [(1, 7, b'x')])

    def test_prime_replay_restart(self):
        wake = WakeEvents()
        self.assertIsNone(wake.accept(99, {}, prime=True))
        self.assertIsNone(wake.accept(99, {}))
        self.assertIsNotNone(wake.accept(100, {}))
        self.assertIsNone(wake.accept(1, {}, prime=True))
        self.assertIsNone(wake.accept(1, {}))

    def test_online_and_single_dispatch(self):
        calls = []
        router = BackendRouter(lambda op, p: calls.append(('aiui', p)) or {'text': 'hello'},
                               lambda op, p: calls.append(('rdk', p)), lambda: True, lambda: 'online')
        self.assertEqual(router.run('asr', b'pcm')[0], 'aiui')
        self.assertEqual(calls, [('aiui', b'pcm')])

    def test_online_error_does_not_use_local(self):
        calls = []
        def online(op, pcm):
            calls.append(('aiui', pcm))
            raise TimeoutError()
        router = BackendRouter(online, lambda op, p: calls.append(('rdk', p)) or {},
                               lambda: True, lambda: 'online')
        with self.assertRaises(TimeoutError): router.run('asr', b'original')
        self.assertEqual(calls, [('aiui', b'original')])

    def test_only_offline_uses_local(self):
        router = BackendRouter(lambda *_: self.fail('cloud called'), lambda *_: {}, lambda: False, lambda: 'offline')
        self.assertEqual(router.run('asr', b'pcm')[0], 'rdk')

    def test_credentials_missing_while_online_is_an_error(self):
        router = BackendRouter(lambda *_: self.fail('cloud called'), lambda *_: self.fail('local called'),
                               lambda: False, lambda: 'online')
        with self.assertRaises(RuntimeError): router.run('asr', b'pcm')

    def test_network_unknown_does_not_use_local(self):
        router = BackendRouter(lambda *_: self.fail('cloud called'), lambda *_: self.fail('local called'),
                               lambda: True, lambda: 'unknown')
        with self.assertRaises(RuntimeError): router.run('asr', b'pcm')

    def test_disconnect_during_cloud_request_allows_local(self):
        state = ['online']
        def online(*_): state[0] = 'offline'; raise OSError()
        router = BackendRouter(online, lambda *_: {}, lambda: True, lambda: state[0])
        self.assertEqual(router.run('asr', b'pcm')[0], 'rdk')

    def test_cancel_never_falls_back(self):
        def cancelled(*_):
            raise InterruptedError()
        router = BackendRouter(cancelled, lambda *_: self.fail('cancel retried'), lambda: True, lambda: 'online')
        with self.assertRaises(InterruptedError):
            router.run('asr', b'pcm')

    def test_no_false_success(self):
        self.assertEqual(parse_result('log\n{"ok":true,"text":"hello"}')["text"], 'hello')
        with self.assertRaises(RuntimeError):
            parse_result('{"ok":false}')

    def test_failed_result_exposes_only_safe_diagnostics(self):
        with self.assertRaises(BackendError) as caught:
            parse_result('SDK log\n{"ok":false,"error_code":20001,"error_scope":"nlp","timed_out":true,"detail":"private token"}')
        self.assertEqual(caught.exception.error_code, 20001)
        self.assertEqual(caught.exception.error_scope, 'nlp')
        self.assertTrue(caught.exception.timed_out)
        self.assertNotIn('private token', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
