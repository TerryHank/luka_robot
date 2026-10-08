import re

def polite_command(text):
 """Only normalize whole, explicit requests; retain targets and negations."""
 t=text.strip()
 t=re.sub(r'^(?:露卡|卢卡)[，,：:\s]*', '', t)
 m=re.fullmatch(r'(?:你)?(?:能不能|可不可以|可以|能)(?:帮我|帮忙)?((?:带我去|带我到|带我过去|去|前往|导航到|找|播放|放一首|暂停音乐|停止音乐|开始巡航).+?)(?:吗|么)?[？?。！!]*',t)
 if m:return m[1]
 m=re.fullmatch(r'((?:带我去|带我到|去|前往|导航到|帮我找|播放|开始巡航).+?)[，,]?(?:好吗|好不好|行吗|可以吗)[？?。！!]*',t)
 return m[1] if m else t

def candidate(text):
 if polite_command(text)!=text.strip():return True
 return any(w in text for w in ('启动','录像','录制','识别','音量','声音','音乐','放歌','播放','来首','听一首','找','带我','跟随','跟着','巡航','巡逻','导航','前往','重定位','声纹','谁在说话','航点','目的地','电梯','建图','配网','联网','注册','账号','房间','地图','功能','状态','音量'))

def direct(text):
 text=polite_command(text)
 if any(w in text for w in ('然后','再去','并且','或者','还是')):
  return {'tool':'clarify','arguments':{}}
 t=re.sub(r'[\s，。！,.!]','',text)
 t=re.sub(r'^(?:露卡|卢卡)[，,:：]?', '', t)
 t=re.sub(r'^(?:麻烦你|麻烦|请你|请)', '', t)
 if t in ('我想知道现在有哪些地方可以去','有哪些地方可以去','你能去哪里','有哪些目的地','有哪些航点'):
  return {'tool':'destinations','arguments':{}}
 m=re.fullmatch(r'我把(.{1,30}?)忘在哪儿了(?:帮忙看看|帮我找找|帮我找一下)',t)
 if m:return {'tool':'find_object','arguments':{'query':m[1]}}
 if re.fullmatch(r'(?:我想|我要)?听(?:一点|一些|点)?(?:轻松|安静|舒缓|好听)的?(?:音乐|歌)',t):
  return {'tool':'clarify','arguments':{}}
 if t in ('带我过去','带我去刚才找到的地方','带我去刚才那个地方'):
  return {'tool':'object_bring','arguments':{}}
 if t in ('继续','继续吧','去那里','去那儿','接着走'):
  return {'tool':'clarify','arguments':{}}
 for phrase,tool in [('跟着我','follow_start'),('开始跟随','follow_start'),('开始跟着我','follow_start'),('停止跟随','follow_stop'),('别跟着我','follow_stop'),('不要跟着我','follow_stop'),('暂停音乐','music_pause'),('暂停播放','music_pause'),('继续播放','music_resume'),('继续音乐','music_resume'),('恢复播放','music_resume'),('停止音乐','music_stop'),('关闭音乐','music_stop'),('停止播放','music_stop'),('现在放的什么歌','music_status'),('有哪些功能','settings_help'),('你能做什么','settings_help'),('查询小车状态','robot_status'),('小车现在怎么样','robot_status')]:
  if t==phrase:return {'tool':tool,'arguments':{}}
 if t in ('调大声音','把声音调大','声音调大','声音大一点','音量大一点'):
  return {'tool':'voice_volume','arguments':{'direction':'up'}}
 if t in ('调小声音','把声音调小','声音调小','声音小一点','音量小一点'):
  return {'tool':'voice_volume','arguments':{'direction':'down'}}
 if t in ('重新定位','自动重定位','开始重定位'):
  return {'tool':'localization_auto','arguments':{}}
 # Speech commonly says “我要听/我想听/听一首”，which must stay a
 # deterministic music action instead of falling through to local chat.
 m=re.fullmatch(r'(?:我(?:要|想)?|请|帮我)?(?:播放|放歌|放一首|来首|来一首|听一首|听)(.{1,80})',t)
 if m and not any(mark in m[1] for mark in ('吗','？','?','怎么','如何')):
  return {'tool':'music_play','arguments':{'query':m[1]}}
 for phrase,tool in [('停止','cancel_all'),('停车','cancel_all'),('停下','cancel_all'),('急停','cancel_all'),('停止导航','cancel_all'),('取消导航','cancel_all'),('别走了','cancel_all'),('停止跟随','follow_stop'),('结束跟随','follow_stop'),('开始录像','record_start'),('停止录像','record_stop'),('查看录像状态','record_status'),('启动小车功能','functions_start'),('查询服务状态','functions_status')]:
  if t==phrase:return {'tool':tool,'arguments':{}}
 from .voice_commands import route
 a=route(t)
 if a:
  routed={'stop':'cancel_all','object_where':'object_where','object_bring':'object_bring','patrol_start':'patrol_start','patrol_stop':'patrol_stop','find_object':'find_object'}
  if a[0] in routed:
   return {'tool':routed[a[0]],'arguments':({'name':a[1]} if a[0]=='navigate' else ({'query':a[1]} if a[1] else {}))}
 # Common ASR prefixes are still deterministic when the destination is
 # explicit; do not send these obvious motion commands through the LLM router.
 m=re.fullmatch(r'(?:请|请你|帮我|我要|我想|让小车|让露卡|小车)?(?:去|到|前往|导航到|带我去|带我到|把我带到)(.{1,40}?)(?:吧)?',t)
 if m:return {'tool':'navigate','arguments':{'name':m[1]}}
 return None
