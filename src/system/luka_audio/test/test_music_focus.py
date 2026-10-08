import unittest
from unittest.mock import patch
from luka_audio import music_focus


class FocusTests(unittest.TestCase):
    def test_volume_restore_respects_a_later_user_change(self):
        calls = []
        with patch.object(music_focus, 'epoch', return_value=2), patch.object(music_focus, 'command', side_effect=lambda *args: calls.append(args) or 8):
            music_focus.restore({'volume': 35, 'epoch': 1})
        self.assertEqual(calls, [])

    def test_volume_restore_returns_original_gain_after_speech(self):
        calls = []
        def command(*args):
            calls.append(args)
            return 8
        with patch.object(music_focus, 'epoch', return_value=1), patch.object(music_focus, 'command', side_effect=command):
            music_focus.restore({'volume': 35, 'epoch': 1})
        self.assertIn(('set_property', 'volume', 35), calls)

    def test_wake_resume_does_not_override_an_explicit_pause(self):
        calls = []
        with patch.object(music_focus, 'epoch', return_value=2), patch.object(music_focus, 'command', side_effect=lambda *args: calls.append(args)):
            music_focus.resume({'path': 'track', 'epoch': 1})
        self.assertEqual(calls, [])

    def test_wake_resume_restores_same_unchanged_track(self):
        calls = []
        def command(*args):
            calls.append(args)
            return 'track' if args[-1] == 'path' else True
        with patch.object(music_focus, 'epoch', return_value=1), patch.object(music_focus, 'command', side_effect=command):
            music_focus.resume({'path': 'track', 'epoch': 1})
        self.assertIn(('set_property', 'pause', False), calls)
