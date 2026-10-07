"""Volatile, bounded speaker-scoped chat histories; no identity carry-over."""
import re,time,sqlite3
from pathlib import Path
DB=Path('/home/sunrise/luka_ws/system/product/voiceprints/profiles.sqlite3')
def enrolled():
 try:
  with sqlite3.connect('file:'+str(DB)+'?mode=ro',uri=True,timeout=1) as c:
   return {i:n for i,n in c.execute('SELECT id,name FROM profiles WHERE ready=1')}
 except sqlite3.Error:return {}

def speaker_key(envelope,profiles,now=None):
 now=time.time() if now is None else now
 s=envelope.get('speaker') or {}
 age=now-envelope.get('captured_at',0)
 if not isinstance(s,dict) or not 0<=age<=15:return None
 score=s.get('similarity',0)
 if s.get('state')!='candidate' or type(score) not in (int,float) or score<.75:return None
 ident=s.get('profile_id')
 return ident if ident in profiles else None

class SpeakerMemories:
 def __init__(self,factory):self.factory=factory;self.items={}
 def get(self,key,profiles):
  for old in list(self.items):
   if old!='web' and old not in profiles:
    self.items.pop(old).clear()
  if key is None:return self.factory() # Unknown guests never inherit another person's history.
  if key!='web' and key not in profiles:return self.factory()
  if key not in self.items:self.items[key]=self.factory()
  return self.items[key]
