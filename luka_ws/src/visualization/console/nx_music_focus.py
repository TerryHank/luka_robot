"""Short local mpv IPC calls for speech/audio focus; never starts playback."""
import json,socket
from pathlib import Path
SOCKET='/home/sunrise/luka_ws/system/music/player.sock'
def command(*args):
 if not Path(SOCKET).exists():return None
 try:
  with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as s:
   s.settimeout(.15);s.connect(SOCKET);s.sendall((json.dumps({'command':list(args),'request_id':73})+'\n').encode())
   f=s.makefile('rb')
   for _ in range(10):
    d=json.loads(f.readline(16384))
    if d.get('request_id')==73:return d.get('data')
 except (OSError,ValueError):pass
 return None
def pause():command('set_property','pause',True)
def duck():
 v=command('get_property','volume')
 if isinstance(v,(int,float)) and v>8:command('set_property','volume',8);return v
 return None
def restore(v):
 if v is not None and command('get_property','volume')==8:command('set_property','volume',v)
