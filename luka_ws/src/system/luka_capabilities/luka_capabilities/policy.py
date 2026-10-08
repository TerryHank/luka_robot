import re
from .catalog import TOOLS, READ_ONLY, TRIGGERS
from .direct_router import polite_command,direct
from .grounding import validate_grounding

def validate(tool,args,source):
 if not isinstance(source,str) or not 1<=len(source)<=1000:raise ValueError('原话无效')
 if tool not in TOOLS or not isinstance(args,dict):raise ValueError('未接通的功能，不执行')
 if tool not in READ_ONLY:
  intent=polite_command(source)
  explicit_stop=tool in ('cancel_all','patrol_stop','follow_stop') and (direct(intent) or {}).get('tool')==tool
  if not explicit_stop and any(w in intent for w in ('不要','不用','不想','别去','能不能','是否','吗','？','?','然后','再去','并且','或者','还是','不播放','别播放','不要启动','不去','不需要','先不','例如','假如','如果','他说','怎么','如何')):raise ValueError('请明确说出一个要执行的动作')
  if not any(w in source for w in TRIGGERS.get(tool,[])):raise ValueError('原话没有明确要求执行这个动作')
 if tool=='music_volume':
  v=args.get('volume')
  if type(v) is not int or not 0<=v<=100 or not re.search(r'(?<![0-9])'+str(v)+r'(?![0-9])',source):raise ValueError('请说出0到100的音乐音量数字')
 if tool in ('find_object','camera_find','music_search','music_play') and not args.get('query'):raise ValueError('请明确说出物品或歌名')
 if 'dwell_s' in args and '秒' in source:
  v=args['dwell_s']
  if type(v) not in (int,float) or not 0<=v<=60 or not re.search(r'(?<![0-9])'+re.escape(str(v))+r'\s*秒',source):raise ValueError('停留秒数必须来自原话')
 if tool=='voice_volume':
  if args.get('direction') not in ('up','down') or not any(w in source for w in (('大','高') if args['direction']=='up' else ('小','低'))):raise ValueError('请明确说调大或调小说话音量')
 validate_grounding(args,source)
