"""One-time maintenance: bind the sole ready owner voice and face records."""
import sqlite3
from pathlib import Path

from identity import IdentityStore


FACE_DB = Path('/home/sunrise/luka_ws/perception/person_follow/data/people.sqlite3')
VOICE_DB = Path('/home/sunrise/luka_ws/system/product/voiceprints/profiles.sqlite3')

with sqlite3.connect(VOICE_DB.resolve().as_uri() + '?mode=ro', uri=True) as db:
    voices = db.execute("SELECT id FROM profiles WHERE name=? AND ready=1", ('主人',)).fetchall()

store = IdentityStore(FACE_DB)
try:
    faces = [p for p in store.list_profiles() if p['name'] == '主人']
    if len(faces) != 1 or len(voices) != 1:
        raise RuntimeError('Owner face and ready voice records must each be unique')
    link = store.bind_voice_profile(faces[0]['id'], voices[0][0])
    print('owner_link_state=' + link['state'])
finally:
    store.close()
