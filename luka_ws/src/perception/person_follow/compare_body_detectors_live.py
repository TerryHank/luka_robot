"""Short read-only detector comparison on current low camera; no images saved."""
import base64
import json
import time
from pathlib import Path
from urllib.request import urlopen

import cv2
import numpy as np

from vision import PeopleNetDetector, PersonDetector

root = Path(__file__).resolve().parent
models = [('yolo', PersonDetector('/home/sunrise/luka_ws/perception/spatial_memory/models/yolo11n-fp16.engine', confidence=.18)),
          ('peoplenet', PeopleNetDetector(root / 'models/resnet34_peoplenet_fp16.engine', confidence=.40))]
results = {name: [] for name, _ in models}
last = None
try:
    while sum(len(rows) for rows in results.values()) < 40:
        with urlopen('http://127.0.0.1:8097/api/people/status', timeout=2) as response:
            status = json.load(response)
        if status.get('frame_at') == last or not status.get('frame_jpeg_base64'):
            time.sleep(.15)
            continue
        last = status['frame_at']
        image = cv2.imdecode(np.frombuffer(base64.b64decode(status['frame_jpeg_base64']), np.uint8), cv2.IMREAD_COLOR)
        for name, detector in models:
            boxes = detector.detect(image)
            results[name].append([(round(item['confidence'], 2), [round(v) for v in item['bbox']]) for item in boxes])
        time.sleep(.1)
finally:
    for _, detector in models:
        detector.close()
for name, frames in results.items():
    print(name, 'frames', len(frames), 'with_person', sum(bool(row) for row in frames),
          'median_count', np.median([len(row) for row in frames]),
          'sample', frames[::5], flush=True)
