"""Print aggregate quality of enrolled face templates; never print embeddings."""
from pathlib import Path
import sqlite3
import numpy as np

db = Path(__file__).resolve().parent / 'data' / 'people.sqlite3'
con = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
try:
    for profile_id, name in con.execute('SELECT id,name FROM profiles'):
        rows = con.execute('SELECT ordinal,embedding FROM samples WHERE profile_id=? ORDER BY ordinal',
                           (profile_id,)).fetchall()
        vectors = np.stack([np.frombuffer(blob, dtype='<f4') for _, blob in rows])
        sims = vectors @ vectors.T
        print('profile=%s count=%d' % (name, len(rows)))
        for start in range(0, len(rows), 12):
            indexes = slice(start, min(start + 12, len(rows)))
            sub = sims[indexes, indexes]
            off = sub[np.triu_indices(len(sub), 1)]
            closest = np.max(sims[indexes] - np.eye(len(rows))[indexes] * 2, axis=1)
            print('batch %02d-%02d: pair median %.3f, pair min %.3f, nearest median %.3f, nearest min %.3f' %
                  (start, min(start + 12, len(rows)) - 1, float(np.median(off)),
                   float(np.min(off)), float(np.median(closest)), float(np.min(closest))))
        for a in range(0, len(rows), 12):
            for b in range(a + 12, len(rows), 12):
                cross = sims[a:min(a + 12, len(rows)), b:min(b + 12, len(rows))]
                print('cross %02d-%02d: median %.3f, max %.3f' %
                      (a, b, float(np.median(cross)), float(np.max(cross))))
finally:
    con.close()
