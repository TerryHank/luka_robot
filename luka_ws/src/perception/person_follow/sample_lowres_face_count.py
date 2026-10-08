"""Read-only diagnostic of one-face duplicate gate, without saving images."""
import base64
import json
import time
from collections import Counter
from pathlib import Path
from urllib.request import urlopen

import cv2
import numpy as np

from vision import FaceFeatures

root = Path(__file__).resolve().parent
faces = FaceFeatures(root / 'models/yunet.onnx', root / 'models/sface.onnx')
counts = Counter()
last = None
for _ in range(20):
    with urlopen('http://127.0.0.1:8097/api/people/status', timeout=2) as response:
        status = json.load(response)
    if status.get('frame_at') != last and status.get('frame_jpeg_base64'):
        image = cv2.imdecode(np.frombuffer(base64.b64decode(status['frame_jpeg_base64']), np.uint8), cv2.IMREAD_COLOR)
        counts[faces.count_faces(image, [0, 0, image.shape[1], image.shape[0]])] += 1
        last = status['frame_at']
    time.sleep(.2)
print('lowres_face_counts', dict(counts))
