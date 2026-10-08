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
    def announcer(self):
        a=ObjectAnnouncer.__new__(ObjectAnnouncer);a.selected_job={'query':'杯子','id':'old','hits':[{}]};return a
    def test_latest_result_supersedes_selection(self):
        a=self.announcer();job={'query':'剪刀','id':'new','session':'s','hits':[{}]}
        with patch('nx_object_announcer.read',return_value={'job':job}):self.assertEqual(a.bring_job()['id'],'new')
    def test_wrong_object_does_not_navigate(self):
        a=self.announcer()
        with patch('nx_object_announcer.read',return_value={'job':{'query':'杯子','hits':[{}]},'sessions':[]}):
            with self.assertRaisesRegex(ValueError,'剪刀'):a.bring_job('剪刀')
    def test_new_search_without_hit_does_not_use_old_selection(self):
        a=self.announcer()
        for status in ('searching','complete'):
            with patch('nx_object_announcer.read',return_value={'job':{'query':'剪刀','status':status,'hits':[]}}):
                with self.assertRaises(ValueError):a.bring_job()
    def test_explicit_archived_object(self):
        a=self.announcer();job={'query':'剪刀','id':'saved','session':'s','hits':[{}]}
        def read(path):return {'job':{'query':'杯子'},'sessions':[{'id':'s'}]} if path=='/patrol/status' else [job]
        with patch('nx_object_announcer.read',side_effect=read):self.assertEqual(a.bring_job('剪刀')['id'],'saved')
    def test_gateway_does_not_send_to_chat(self):
        # Exercise the actual gateway method with HTTP and audio replaced; no robot IO.
        source=ast.parse(Path(__file__).with_name('nx_voice_gateway.py').read_text(encoding='utf-8'))
        cls=next(x for x in source.body if isinstance(x,ast.ClassDef) and x.name=='NXVoiceGateway')
        method=next(x for x in cls.body if isinstance(x,ast.FunctionDef) and x.name=='_publish_command')
        import urllib.request,urllib.error,time,threading
        ns=dict(route=route,destination_intent=destination_intent,correct_room_command=correct_room_command,
                deduplicate_command=lambda t:t,clean_command=lambda t,w:t,String=lambda **kw:kw,
                urllib=urllib,json=json,time=time,threading=threading)
        exec(compile(ast.Module(body=[method],type_ignores=[]),'gateway_method','exec'),ns)
        n=SimpleNamespace(wake_word='露卡',text_pub=Mock(),_status=Mock(),_return_to_wake=Mock(),say=Mock(),object_announcer=Mock())
        n.object_announcer.bring_job.return_value={'id':'hit','session':'s','query':'剪刀'}
        for phrase in ('带我去','带我去找剪刀','找剪刀'):
            with patch('urllib.request.urlopen',return_value=io.BytesIO(b'{"ok":true,"message":"ok"}')) as call:
                ns['_publish_command'](n,phrase)
                req=call.call_args.args[0]
                self.assertTrue(req.full_url.endswith('/bring' if phrase.startswith('带') else '/find'))
                self.assertEqual(json.loads(req.data)['query'],'剪刀')
        n.object_announcer.bring_job.side_effect=ValueError('未找到剪刀')
        with patch('urllib.request.urlopen') as call:
            ns['_publish_command'](n,'带我去找剪刀');call.assert_not_called()
        n.voiceprint=Mock();n.sample_rate=16000;n._voiceprint_audio=[.1]*100
        with patch('urllib.request.urlopen') as call:
            ns['_publish_command'](n,'带我去找剪刀');call.assert_not_called()
            n.voiceprint.submit.assert_called_once()
        n._voiceprint_audio=[.1]*100
        with patch('urllib.request.urlopen',return_value=io.BytesIO(b'{"ok":true,"message":"stopped"}')) as call:
            ns['_publish_command'](n,'停止导航')
            self.assertTrue(call.call_args.args[0].full_url.endswith('/api/nav/stop'))
    def test_bring_finishes_selected_search_before_navigation(self):
        import threading,time
        from nx_patrol_mission import PatrolMission
        m=PatrolMission.__new__(PatrolMission);m.lock=threading.RLock();m.cancel=threading.Event();m.active=lambda:False
        m.node=SimpleNamespace(nx_handle=None,relocalization=SimpleNamespace(running=False),pose=True,last={'pose':time.monotonic(),'scan':time.monotonic()})
        m.target=lambda body:{'job_id':'chosen','query':'剪刀','display_name':'剪刀观察位置'}
        m.update=Mock();calls=[];job={'id':'chosen','status':'searching'}
        def vision(path,body=None):
            calls.append(path)
            if path=='/patrol/cancel':job['status']='cancelled'
            return {'job':job,'recording':None}
        with patch('nx_patrol_mission.vision',side_effect=vision),patch('nx_patrol_mission.threading.Thread') as thread:
            self.assertTrue(m.bring({})['ok']);thread.return_value.start.assert_called_once()
        self.assertLess(calls.index('/patrol/cancel'),calls.index('/model/unload'))
        job.update(id='different',status='searching');calls.clear()
        with patch('nx_patrol_mission.vision',side_effect=vision),patch('nx_patrol_mission.threading.Thread') as thread:
            with self.assertRaisesRegex(ValueError,'另一个'):m.bring({})
            thread.assert_not_called();self.assertNotIn('/patrol/cancel',calls)

if __name__=='__main__':unittest.main()
