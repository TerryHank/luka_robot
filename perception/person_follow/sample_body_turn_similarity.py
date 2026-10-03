"""Read-only, ephemeral body descriptor quality diagnostic; prints scores only."""
import base64
import json
import time
from pathlib import Path
from urllib.request import urlopen

import cv2
import numpy as np

from appearance import BodyAppearance

model = BodyAppearance(Path(__file__).resolve().parent / 'models/osnet_x0_25_msmt17.onnx')
first = None
previous = None
records = []
last_stamp = None
end = time.monotonic() + 20
while time.monotonic() < end:
    try:
        with urlopen('http://127.0.0.1:8097/api/people/status', timeout=2) as response:
            status = json.load(response)
        stamp = status.get('frame_at')
        if stamp == last_stamp or not status.get('frame_jpeg_base64'):
            time.sleep(.16)
            continue
        last_stamp = stamp
        tracks = status.get('tracks') or []
        if not tracks:
            records.append(dict(track=None))
            time.sleep(.16)
            continue
        person = next((row for row in tracks if row.get('selected')), None)
        if person is None:
            person = max(tracks, key=lambda row: (row['bbox'][2]-row['bbox'][0]) *
                         (row['bbox'][3]-row['bbox'][1]))
        image = cv2.imdecode(np.frombuffer(base64.b64decode(status['frame_jpeg_base64']), np.uint8), cv2.IMREAD_COLOR)
        vector = model.embed(image, person['bbox'])
        if vector is None:
            records.append(dict(track=person.get('track_id'), score=None))
        else:
            if first is None:
                first = vector
            records.append(dict(track=person.get('track_id'),
                                to_first=round(float(np.dot(vector, first)), 3),
                                to_previous=round(float(np.dot(vector, previous)), 3) if previous is not None else None,
                                bbox=[round(value) for value in person['bbox']]))
            previous = vector
    except Exception as error:
        records.append(dict(error=type(error).__name__))
    time.sleep(.16)
print('frames', len(records))
print('track_ids', sorted({row['track'] for row in records if row.get('track') is not None}))
scores = [row['to_first'] for row in records if row.get('to_first') is not None]
adjacent = [row['to_previous'] for row in records if row.get('to_previous') is not None]
print('to_first', dict(min=min(scores), median=float(np.median(scores)), max=max(scores)) if scores else None)
print('adjacent', dict(min=min(adjacent), median=float(np.median(adjacent)), max=max(adjacent)) if adjacent else None)
print('timeline', [(row.get('track'), row.get('to_first'), row.get('to_previous')) for row in records[::4]])
