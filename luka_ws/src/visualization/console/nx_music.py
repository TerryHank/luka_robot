"""Music provider adapter and local mpv controls; failures never imply playback."""
import json,urllib.request,urllib.parse,subprocess,threading,socket,time,ipaddress,os,signal
from pathlib import Path
from nx_music_settings import load_volume,save_volume

def tracks(data):
 rows=data.get('result',data.get('data',[])) if isinstance(data,dict) else []
 if isinstance(rows,dict):rows=rows.get('songs',rows.get('list',[]))
 out=[]
 if not isinstance(rows,list):return out
 for row in rows[:30]:
  if not isinstance(row,dict):continue
  url=row.get('url') or row.get('play_url')
  if not isinstance(url,str) or urllib.parse.urlparse(url).scheme not in ('https','http'):continue
  out.append({'title':str(row.get('title') or row.get('name') or '未知歌曲')[:100],'artist':str(row.get('author') or row.get('artist') or '')[:100],'url':url})
 return out

def public_url(url):
 u=urllib.parse.urlparse(url)
 if u.scheme not in ('https','http') or not u.hostname or u.username or u.password:raise ValueError('歌曲链接格式不支持')
 for a in socket.getaddrinfo(u.hostname,u.port or (443 if u.scheme=='https' else 80),type=socket.SOCK_STREAM):
  if not ipaddress.ip_address(a[4][0]).is_global:raise ValueError('歌曲链接不能访问内网地址')

class SafeRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,req,fp,code,msg,headers,newurl):
  public_url(newurl);return super().redirect_request(req,fp,code,msg,headers,newurl)

class Music:
 def __init__(self):
  self.lock=threading.RLock();self.proc=None;self.title='';self.error='';self.volume=load_volume();self.paused=False
  self.root=Path('/home/sunrise/luka_data/runtime/music');self.root.mkdir(exist_ok=True,parents=True);self.ipc=str(self.root/'player.sock')
 def search(self,query):
  from nx_alapi_music import search
  return search(query)
 def command(self,*args):
  if not self.proc or self.proc.poll() is not None:raise ValueError('当前没有正在播放的歌曲')
  with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as s:
   s.settimeout(2);s.connect(self.ipc);s.sendall((json.dumps({'command':list(args),'request_id':1})+'\n').encode())
   f=s.makefile('rb')
   for _ in range(30):
    reply=json.loads(f.readline(65536))
    if reply.get('request_id')==1:break
   else:raise ValueError('播放器控制响应超时')
   if reply.get('error')!='success':raise ValueError('播放器未接受控制指令')
   return reply.get('data')
 def stop(self):
  if self.proc and self.proc.poll() is None:
   os.killpg(self.proc.pid,signal.SIGTERM)
   try:self.proc.wait(timeout=3)
   except subprocess.TimeoutExpired:os.killpg(self.proc.pid,signal.SIGKILL);self.proc.wait()
  self.proc=None;self.paused=False
 def mark_control(self,kind):
  file=self.root/'focus_epoch.json'
  try:state=json.loads(file.read_text())
  except (OSError,ValueError):state={'transport':0,'volume':0}
  field='volume' if kind=='volume' else 'transport'
  state[field]=int(state.get(field,0))+1
  temp=file.with_suffix('.tmp');temp.write_text(json.dumps(state));temp.replace(file)
 def action(self,kind,args,cancel=None):
  with self.lock:
   try:
    if kind=='status' and self.proc and self.proc.poll() is None:self.paused=bool(self.command('get_property','pause'))
    if kind=='status':return ('已暂停：' if self.paused else '正在播放：')+self.title if self.proc and self.proc.poll() is None else '音乐未在播放。'+self.error
    if kind in ('search','play'):
     if cancel is not None and cancel.is_set():raise InterruptedError('music_cancelled')
     rows=self.search(args.get('query'))
     if kind=='search':return '找到：'+'；'.join(r['title']+' '+r['artist'] for r in rows[:5])
     from nx_alapi_music import resolve
     track=resolve(rows[0]);public_url(track['url'])
     # Download bounded public audio before passing a local file to the decoder.
     opener=urllib.request.build_opener(SafeRedirect());p=self.root/'current.audio.part';total=0;deadline=time.monotonic()+10
     with opener.open(track['url'],timeout=5) as r,p.open('wb') as f:
      if 'html' in r.headers.get('Content-Type','').lower():raise ValueError('歌曲地址返回网页，无法播放')
      while True:
       if cancel is not None and cancel.is_set():raise InterruptedError('music_cancelled')
       chunk=r.read(65536)
       if not chunk:break
       if time.monotonic()>deadline:raise ValueError('歌曲下载超时')
       total+=len(chunk)
       if total>30_000_000:raise ValueError('歌曲文件过大，取消播放')
       f.write(chunk)
     if cancel is not None and cancel.is_set():raise InterruptedError('music_cancelled')
     self.stop();audio=self.root/'current.audio';p.replace(audio);audio.chmod(0o644)
     try:Path(self.ipc).unlink()
     except FileNotFoundError:pass
     cmd=['/usr/bin/mpv','--no-config','--no-video','--ytdl=no','--load-unsafe-playlists=no','--audio-device=alsa/luka_mix','--volume='+str(self.volume),'--input-ipc-server='+self.ipc,str(audio)]
     if os.geteuid()==0:cmd=['/usr/sbin/runuser','-u','sunrise','--']+cmd
     log=(self.root/'player.log').open('w');self.proc=subprocess.Popen(cmd,stdout=log,stderr=log,start_new_session=True);log.close()
     end=time.monotonic()+5
     while time.monotonic()<end:
      if cancel is not None and cancel.is_set():self.stop();raise InterruptedError('music_cancelled')
      if self.proc.poll() is not None:raise ValueError('播放器启动失败，请查看音乐状态')
      try:
       if self.command('get_property','time-pos') is not None:break
      except (OSError,ValueError):pass
      time.sleep(.1)
     else:self.stop();raise ValueError('播放器未开始播放')
     duration=self.command('get_property','duration')
     expected=track.get('duration_ms',0)
     preview=isinstance(expected,(int,float)) and expected>0 and isinstance(duration,(int,float)) and duration*1000<expected*.8
     self.title=('试听片段：' if preview else '')+track['title']+('，'+track['artist'] if track['artist'] else '');self.paused=False;self.error='';self.mark_control(kind);return '正在播放'+self.title+'。'
    if kind=='stop':self.stop();self.mark_control(kind);return '音乐已停止。'
    if kind in ('pause','resume'):
     self.command('set_property','pause',kind=='pause');self.paused=kind=='pause';self.mark_control(kind);return '音乐已暂停。' if self.paused else '音乐已继续。'
    if kind=='volume':
     v=args.get('volume')
     if type(v) is not int or not 0<=v<=100:raise ValueError('音量须为0到100')
     if self.proc and self.proc.poll() is None:self.command('set_property','volume',v)
     save_volume(v)
     self.volume=v;self.mark_control(kind);return '音乐音量已设为'+str(v)+'。'
    raise ValueError('不支持的音乐操作')
   except Exception as exc:
    self.error=str(exc);raise
