import ast
from pathlib import Path
import re, time, queue, threading
from collections import OrderedDict
from types import SimpleNamespace
from unittest.mock import Mock
import numpy as np

source = Path(__file__).with_name('voice_gateway.py')
tree = ast.parse(source.read_text())
selected = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ('speech_segments', 'speech_pcm')]
cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'VoiceGateway')
cls.bases = []
cls.body = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in ('_speech_audio', '_speak_loop')]
ns = dict(np=np, re=re, time=time, queue=queue)
exec(compile(ast.Module(body=selected+[cls], type_ignores=[]), str(source), 'exec'), ns)
split, pcm = ns['speech_segments'], ns['speech_pcm']
for text in ('好，这就带你去厨房。', '第一句话。第二句话！第三句话？', '长回答，'*35, '温度是23.5度。'):
    parts = split(text)
    assert ''.join(parts) == text and all(len(p) <= 40 for p in parts)
assert split('') == []
samples = np.array([.1, -.2, .05], dtype=np.float32)
plain = pcm(samples, 16000, 1.0, 4.0, 0)
padded = pcm(samples, 16000, 1.0, 4.0, .2)
assert padded[:6400] == bytes(6400) and padded[6400:] == plain
assert np.allclose(samples, [.1, -.2, .05])
for bad in ([], [float('nan')]):
    try: pcm(bad,16000,1,4,.2)
    except ValueError: pass
    else: raise AssertionError('invalid audio accepted')
n = ns['VoiceGateway']()
n.tts_sid=14; n.tts_speed=1.08; n._speech_cache=OrderedDict(); n._speech_cache_bytes=0
n.tts=SimpleNamespace(generate=Mock(return_value=SimpleNamespace(samples=samples, sample_rate=16000)))
assert n._speech_audio('测试')[1] is False
assert n._speech_audio('测试')[1] is True
assert n.tts.generate.call_count == 1
n.tts_sid=0
assert n._speech_audio('测试')[1] is False
for i in range(70): n._speech_audio(str(i))
assert len(n._speech_cache)==64
# Run complete segmented output with a fake player; NEVER open audio hardware.
n.stop_event=threading.Event(); n.speak_queue=queue.Queue(); n.speak_queue.put('第一句。第二句。')
n._wake_audio=None; n.wake_response='在呢'; n.tts_volume=1; n.tts_max_gain=4
n.speaker_device='fake'; n.tts_playing=threading.Event(); n._tts_guard_lock=threading.Lock()
n.tts_echo_guard=.7; n.wake_echo_guard=.2
n.get_parameter=lambda _: SimpleNamespace(value=.2)
n._status=Mock(); n.get_logger=Mock(return_value=Mock())
plays=[]
class Player:
    def __init__(self,*args,**kwargs): assert n.tts_playing.is_set()
    def communicate(self,input,timeout):
        assert n.tts_playing.is_set() and input[:6400]==bytes(6400)
        plays.append(input)
        if len(plays)==2: n.stop_event.set()
ns['subprocess']=SimpleNamespace(Popen=Player, PIPE=-1)
n._speak_loop()
assert len(plays)==2 and not n.tts_playing.is_set() and n._tts_resume_at>time.monotonic()
print('PASS: splitting, PCM prefix/no truncation, invalid audio, cache/key/eviction, ordered playback, inter-segment echo guard')
