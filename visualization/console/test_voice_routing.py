import unittest
from unittest.mock import Mock, patch
from nx_voice_commands import route,hold_level
from nx_voice_gateway import NXVoiceGateway
import numpy as np
import time
import io

class VoiceTests(unittest.TestCase):
    def test_motion_phrases(self):
        for text,poi in [('去厨房','wp_008'),('请带我去卧室吧','wp_009'),('导航到浴室。','wp_010')]:
            self.assertEqual(route(text),('navigate',poi))
        for text in ['不要去卧室','去卧室又死了，看','去厨房还是浴室','你能去卧室吗','刚才说去厨房','去三楼','开始巡航','不停下来']:
            self.assertIsNone(route(text),text)
        self.assertEqual(route('停止导航'),('stop',None))

    def test_dispatch_uses_real_dashboard_without_agent(self):
        node=NXVoiceGateway.__new__(NXVoiceGateway)
        node.wake_word='露卡';node.text_pub=Mock();node.command_pub=Mock()
        node._return_to_wake=Mock();node.say=Mock();node._status=Mock()
        for text,path,body in [('去浴室','/api/nav',b'{"id": "wp_010"}'),('停止导航','/api/nav/stop',b'{}')]:
            with patch('urllib.request.urlopen',return_value=io.BytesIO('{"ok":true,"display_name":"浴室"}'.encode())) as call:
                node._publish_command(text)
                req=call.call_args.args[0]
                self.assertEqual(req.full_url,'http://127.0.0.1:8503'+path)
                self.assertEqual(req.data,body)
                node.command_pub.publish.assert_not_called()
        with patch('urllib.request.urlopen',side_effect=TimeoutError()) as call:
            node._publish_command('去卧室')
            self.assertEqual(call.call_count,1)
            self.assertIn('未能确认',node.say.call_args.args[0])

    def test_noisy_endpoint(self):
        node=NXVoiceGateway.__new__(NXVoiceGateway)
        node.manual_control=lambda:False
        node.noise_floor=.004;node.command_peak=0
        node.chunk_seconds=.1;node.sample_rate=16000
        node.command_pre_roll=.6;node.command_start_frames=2
        node.command_min_speech=.4;node.command_min_utterance=.8
        node.command_end_silence=.6;node.command_deadline=time.monotonic()+10
        node._status=Mock();node._recognize_command=Mock()
        node._reset_command_capture()
        # Speech followed by fluctuating background that exceeded the old hold gate.
        for level in [.08]*10+[.008,.009]*4:
            node._process_command(np.full(1600,level,dtype=np.float32))
            if node._recognize_command.called:break
        node._recognize_command.assert_called_once()
        self.assertLess(node.command_elapsed,2)
        self.assertAlmostEqual(node.noise_floor,.004)
        self.assertLessEqual(hold_level(.004,1),.025)

if __name__=='__main__':unittest.main(verbosity=2)
