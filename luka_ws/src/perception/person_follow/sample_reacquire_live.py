"""Read-only short diagnostic of target recovery; no images or biometric data."""
import json
import time
from urllib.request import urlopen

last = None
deadline = time.monotonic() + 65
while time.monotonic() < deadline:
    try:
        with urlopen('http://127.0.0.1:8097/api/people/status', timeout=2) as response:
            status = json.load(response)
        tracks = status.get('tracks') or []
        target = status.get('target_session') or {}
        pending = status.get('face_reacquire') or {}
        current = (target.get('state'), target.get('track_id'), target.get('reason'),
                   pending.get('active'), pending.get('wait_reason'), pending.get('confirmation_count'),
                   tuple((t.get('track_id'), (t.get('identity') or {}).get('state'),
                       round((t.get('identity') or {}).get('similarity') or 0., 2)) for t in tracks))
        if current != last:
            print(round(time.monotonic(), 1), current, flush=True)
            last = current
    except Exception as exc:
        print('error', type(exc).__name__, flush=True)
    time.sleep(.2)
