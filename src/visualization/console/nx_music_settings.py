"""Atomic local playback preferences. Invalid files fall back to a safe default."""
import json,os
from pathlib import Path
DEFAULT=Path('/home/sunrise/luka_data/runtime/music/settings.json')
def load_volume(path=DEFAULT):
 try:
  v=json.loads(Path(path).read_text())['volume']
  if type(v) is int and 0<=v<=100:return v
 except (OSError,ValueError,KeyError,TypeError):pass
 return 35

def save_volume(v,path=DEFAULT):
 if type(v) is not int or not 0<=v<=100:raise ValueError('音量须为0到100')
 path=Path(path);path.parent.mkdir(exist_ok=True,parents=True)
 tmp=path.with_suffix('.tmp')
 with tmp.open('w') as f:
  json.dump({'volume':v},f);f.flush();os.fsync(f.fileno())
 tmp.chmod(0o600);tmp.replace(path)
