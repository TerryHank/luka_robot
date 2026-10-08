"""ALAPI music metadata and playable URLs; credentials remain on the robot."""
import json,time,threading,urllib.request,urllib.error
from pathlib import Path
BASE='https://v3.alapi.cn/api/music/'
_lock=threading.Lock()
_last=0.0

def request(action,params):
 global _last
 if action not in ('search','url'):raise ValueError('不支持的音乐接口')
 try:token=json.loads(Path('/home/sunrise/.config/luka_music/alapi.json').read_text())['token']
 except (OSError,ValueError,KeyError):raise ValueError('音乐服务尚未配置 token') from None
 with _lock:
  for attempt in range(2):
   time.sleep(max(0,1.2-(time.monotonic()-_last)))
   req=urllib.request.Request(BASE+action,data=json.dumps(params).encode(),headers={'token':token,'Content-Type':'application/json'})
   try:
    with urllib.request.urlopen(req,timeout=7) as r:raw=r.read(2_000_001)
   except urllib.error.HTTPError as e:
    _last=time.monotonic()
    if e.code==429 and attempt==0:time.sleep(1.5);continue
    raise ValueError('音乐服务请求失败，HTTP '+str(e.code)) from None
   except (OSError,urllib.error.URLError):raise ValueError('音乐服务连接超时或网络异常') from None
   finally:_last=time.monotonic()
   if len(raw)>2_000_000:raise ValueError('音乐服务返回过大')
   try:d=json.loads(raw)
   except ValueError:raise ValueError('音乐服务未返回有效JSON') from None
   if not isinstance(d,dict):raise ValueError('音乐服务数据格式异常')
   if d.get('code')==429 and attempt==0:time.sleep(1.5);continue
   if d.get('code')!=200 or d.get('success') is False:
    # Never surface raw provider messages which might echo credentials.
    raise ValueError('音乐服务拒绝请求（代码'+str(d.get('code','未知'))+'），请检查 token、接口额度或稍后重试')
   return d.get('data')
 raise ValueError('音乐接口请求频繁，请稍后重试')

def songs(data):
 rows=data.get('songs',[]) if isinstance(data,dict) else []
 if not isinstance(rows,list):return []
 out=[]
 for r in rows[:10]:
  if not isinstance(r,dict) or not str(r.get('id','')).isdigit():continue
  artists=r.get('artists') or r.get('ar') or []
  out.append({'id':str(r['id']),'duration_ms':r.get('duration',r.get('dt',0)),'title':str(r.get('name') or '未知歌曲')[:100], 'artist':'、'.join(str(a.get('name','')) for a in artists if isinstance(a,dict))[:100]})
 return out

def search(query):
 if not isinstance(query,str) or not 1<=len(query.strip())<=80:raise ValueError('请说出歌名或歌手')
 result=songs(request('search',{'keyword':query.strip(),'limit':'5','type':'1','page':'1'}))
 if not result:raise ValueError('没有搜索到这首歌，请补充歌名或歌手')
 # Prefer an exact title, preserving provider rank for other matches.
 return sorted(result,key=lambda s:s['title']!=query.strip())

def resolve(track):
 data=request('url',{'id':track['id']})
 if isinstance(data,list):data=next((d for d in data if isinstance(d,dict) and str(d.get('id'))==track['id']),{})
 if not isinstance(data,dict) or not isinstance(data.get('url'),str) or not data['url'].startswith(('https://','http://')):raise ValueError('搜到了'+track['title']+'，但平台没有提供可播放链接，可能需要会员或暂无播放权限')
 return dict(track,url=data['url'])
