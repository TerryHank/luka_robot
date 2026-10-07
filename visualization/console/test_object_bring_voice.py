import ast,io,json,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from nx_voice_commands import route,destination_intent,correct_room_command
from nx_object_announcer import ObjectAnnouncer

class ObjectVoiceTests(unittest.TestCase):
    def test_phrases(self):
        for text in ['带我去','带我去吧','请带我过去','带我去看看']:
            self.assertEqual(route(text),('object_bring',None))
        for text in ['带我去找剪刀','请带我去找剪刀吧','带我去剪刀的位置','带我去看看剪刀']:
            self.assertEqual(route(text),('object_bring','剪刀'))
        for text in ['找剪刀','找一下剪刀','帮我找剪刀','请找剪刀吧']:
            self.assertEqual(route(text),('find_object','剪刀'))
        for text in ['不要带我去找剪刀','带我去找剪刀还是杯子','你能带我去找剪刀吗','带我去找剪刀然后去厨房']:
            self.assertIsNone(route(text),text)
        self.assertEqual(route('带我去厨房'),('navigate','wp_008'))
    def test_announcer_uses_map_scoped_mission_api_without_old_video_selection(self):
        announcer=ObjectAnnouncer(SimpleNamespace())
        announcer.selected_job={'query':'杯子','id':'obsolete'}
        with patch('urllib.request.urlopen',return_value=io.BytesIO(b'{"ok":true,"message":"located"}')) as call:
            self.assertEqual(announcer.answer('剪刀'),'located')
            body=json.loads(call.call_args.args[0].data)
            self.assertEqual(body['tool'],'object_where')
            self.assertEqual(body['arguments'],{'query':'剪刀'})
            self.assertNotIn('id',body)
    def test_announcer_preserves_mission_rejection(self):
        with patch('urllib.request.urlopen',return_value=io.BytesIO(b'{"ok":false,"error":"map mismatch"}')):
            with self.assertRaisesRegex(ValueError,'map mismatch'):
                ObjectAnnouncer(SimpleNamespace()).answer('剪刀')
    def test_gateway_does_not_send_to_chat(self):
        # Exercise the actual gateway method with HTTP and audio replaced; no robot IO.
        source=ast.parse(Path(__file__).with_name('nx_voice_gateway.py').read_text(encoding='utf-8'))
        cls=next(x for x in source.body if isinstance(x,ast.ClassDef) and x.name=='NXVoiceGateway')
        method=next(x for x in cls.body if isinstance(x,ast.FunctionDef) and x.name=='_publish_command')
        import urllib.request,urllib.error,time,threading
        ns=dict(route=route,destination_intent=destination_intent,correct_room_command=correct_room_command,
                deduplicate_command=lambda t:t,clean_command=lambda t,w:t,String=lambda **kw:kw,
                urllib=urllib,json=json,time=time,threading=threading,capability_execute=Mock(return_value={'ok':True,'message':'ok'}))
        exec(compile(ast.Module(body=[method],type_ignores=[]),'gateway_method','exec'),ns)
        n=SimpleNamespace(wake_word='露卡',text_pub=Mock(),_status=Mock(),_return_to_wake=Mock(),say=Mock(),object_announcer=Mock(),voice_follow=Mock())
        n.object_announcer.bring_job.return_value={'id':'hit','session':'s','query':'剪刀'}
        for phrase in ('带我去','带我去找剪刀','找剪刀'):
            ns['capability_execute'].reset_mock()
            ns['_publish_command'](n,phrase)
            tool,args,source=ns['capability_execute'].call_args.args
            self.assertEqual(tool,'object_bring' if phrase.startswith('带') else 'find_object')
            self.assertEqual(args,{} if phrase=='带我去' else {'query':'剪刀'})
            self.assertEqual(source,phrase)
        n.object_announcer.bring_job.assert_not_called()
        n.voiceprint=Mock();n.sample_rate=16000;n._voiceprint_audio=[.1]*100
        ns['capability_execute'].reset_mock()
        with patch('urllib.request.urlopen') as call:
            ns['_publish_command'](n,'带我去找剪刀');call.assert_not_called()
            n.voiceprint.submit.assert_called_once()
        ns['capability_execute'].assert_not_called()
        n._voiceprint_audio=[.1]*100
        ns['_publish_command'](n,'停止导航')
        ns['capability_execute'].assert_called_once_with('cancel_all',{},'停止导航')
    def test_bring_rejects_running_semantic_capture_before_navigation(self):
        import threading,time
        from nx_patrol_mission import PatrolMission
        m=PatrolMission.__new__(PatrolMission);m.lock=threading.RLock();m.cancel=threading.Event();m.active=lambda:False;m.generation=0
        m.node=SimpleNamespace(nx_handle=None,relocalization=SimpleNamespace(running=False),pose=True,last={'pose':time.monotonic(),'scan':time.monotonic()})
        m.target=lambda body:{'job_id':'chosen','query':'剪刀','display_name':'剪刀观察位置'}
        m.update=Mock();calls=[];capture={'running':False}
        def vision(path,body=None):
            calls.append(path)
            return capture if path=='/semantic/status' else {'ok':True}
        with patch('nx_patrol_mission.vision',side_effect=vision),patch('nx_patrol_mission.threading.Thread') as thread:
            self.assertTrue(m.bring({})['ok']);thread.return_value.start.assert_called_once()
        self.assertLess(calls.index('/semantic/status'),calls.index('/model/unload'))
        capture['running']=True;calls.clear()
        with patch('nx_patrol_mission.vision',side_effect=vision),patch('nx_patrol_mission.threading.Thread') as thread:
            with self.assertRaisesRegex(ValueError,'实时物体记忆'):m.bring({})
            thread.assert_not_called();self.assertNotIn('/model/unload',calls)

if __name__=='__main__':unittest.main()
