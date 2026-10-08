"""Optional bridge to the household YOLOE TensorRT service on port 8096.

The production 8091 API keeps its existing NanoOWL fallback. Exact household
queries use YOLOE, while descriptive/color queries continue to use NanoOWL.
The bridge also unloads the inactive backend so the two vision models are not
kept in GPU memory together.
"""

from __future__ import annotations

import base64
import json
import pathlib
import time
import urllib.error
import urllib.request

import cv2


BASE_URL = "http://127.0.0.1:8096"
NAMES = {'person'}
ALIASES = {'人': 'person', '人体': 'person', '人员': 'person'}


def canonical(query: str) -> str | None:
    query = query.strip()
    if query in ALIASES:
        return ALIASES[query]
    lowered = query.lower()
    return lowered if lowered in NAMES else None


def _post(path: str, payload: dict, timeout: float = 30.0) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        BASE_URL + path,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def unload() -> None:
    try:
        _post("/model/unload", {}, timeout=2.0)
    except Exception:
        pass


def loaded() -> bool:
    try:
        with urllib.request.urlopen(BASE_URL + "/health", timeout=0.25) as response:
            return bool(json.loads(response.read().decode("utf-8")).get("model_loaded"))
    except Exception:
        return False


def detect_all(frame):
    """One full-resolution frame, one fixed-vocabulary pass; never load NanoOWL."""
    ok, encoded = cv2.imencode('.png', frame, [int(cv2.IMWRITE_PNG_COMPRESSION), 3])
    if not ok:
        raise ValueError('图像编码失败')
    payload = _post('/infer_image', {'all_objects': True,
        'image_base64': base64.b64encode(encoded.tobytes()).decode('ascii')})
    return {'detections': [{'label': d['class'], 'score': d['confidence'], 'box': d['bbox']}
                           for d in payload.get('detections', [])],
            'inference_seconds': payload.get('inference_seconds')}


def locate(image: pathlib.Path, query: str, prefix: pathlib.Path):
    """Return a production-shaped result, or None for NanoOWL fallback."""
    target = canonical(query)
    if target is None:
        return None
    frame = cv2.imread(str(image))
    if frame is None:
        return None
    ok, encoded = cv2.imencode(".png", frame, [int(cv2.IMWRITE_PNG_COMPRESSION), 3])
    if not ok:
        return None
    payload = _post("/infer_image", {"query": query, "image_base64": base64.b64encode(encoded.tobytes()).decode("ascii")})
    detections = [
        {"label": item["class"], "score": item["confidence"], "box": item["bbox"]}
        for item in payload.get("detections", [])
    ]
    marked = frame.copy()
    for detection in detections:
        x1, y1, x2, y2 = map(int, detection["box"])
        cv2.rectangle(marked, (x1, y1), (x2, y2), (0, 220, 120), 2)
        cv2.putText(marked, f"{detection['label']} {detection['score']:.2f}",
                    (x1, max(20, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                    (0, 220, 120), 2, cv2.LINE_AA)
    prefix = pathlib.Path(prefix)
    prefix.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(prefix.with_suffix(".png")), marked)
    result = {
        "image": str(prefix.with_suffix(".png")),
        "prompt": query,
        "backend": "yolo26m-objv1-seg-person-bpu",
        "inference_seconds": payload.get("inference_seconds"),
        "top_scores": [d["score"] for d in detections],
        "detections": detections,
    }
    prefix.with_suffix(".json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return result
