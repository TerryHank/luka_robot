"""NanoOWL TensorRT runtime for the production 8091 endpoint.

The previous LocateAnything runtime remains available as a backup copy on the
NX.  This adapter keeps the existing live_app/patrol API while loading the
NanoOWL image encoder only when a query arrives.
"""

from __future__ import annotations

import ctypes
import json
import pathlib
import threading
import time
from collections import OrderedDict


ALIASES = {
    "鼠标": "computer mouse", "打火机": "lighter", "水杯": "cup", "杯子": "cup",
    "瓶子": "bottle", "手机": "cell phone", "电脑": "laptop", "椅子": "chair",
    "键盘": "keyboard", "书": "book", "遥控器": "remote control", "人": "person",
    "门": "door", "窗户": "window", "桌子": "table", "柜子": "cabinet",
    "冰箱": "refrigerator", "沙发": "sofa", "电视": "television", "显示器": "monitor",
    "背包": "backpack", "包": "bag", "鞋子": "shoe", "眼镜": "glasses",
    "钥匙": "keys", "剪刀": "scissors", "电风扇": "fan", "空调": "air conditioner",
}
DESCRIPTORS = {
    "白色": "white", "黑色": "black", "红色": "red", "蓝色": "blue",
    "绿色": "green", "黄色": "yellow", "灰色": "gray", "棕色": "brown",
    "橙色": "orange", "紫色": "purple", "粉色": "pink",
}
RELATIONS = {
    "靠门的": "near the door ", "门旁边的": "near the door ",
    "桌上的": "on the table ", "桌旁的": "near the table ",
    "柜子里的": "in the cabinet ", "冰箱旁的": "near the refrigerator ",
}


class ModelRuntime:
    def __init__(self, root, idle_seconds: int = 60):
        self.root = pathlib.Path(root)
        self.idle_seconds = idle_seconds
        self.model_dir = pathlib.Path("/home/nvidia/owlvit_model")
        self.engine = pathlib.Path("/home/nvidia/owl_image_encoder_patch32.engine")
        self.predictor = None
        self.text_cache: OrderedDict[str, object] = OrderedDict()
        self.guard = threading.Lock()
        self.last_used = 0.0
        threading.Thread(target=self.reap, daemon=True).start()

    def _ensure(self):
        if self.predictor is not None:
            return
        import nanoowl.owl_predictor as predictor_module
        predictor_module._owl_get_image_size = lambda _: 768
        predictor_module._owl_get_patch_size = lambda _: 32
        from nanoowl.owl_predictor import OwlPredictor
        self.predictor = OwlPredictor(
            model_name=str(self.model_dir), device="cuda",
            image_encoder_engine=str(self.engine),
        )
        self.text_cache.clear()

    @staticmethod
    def _canonical(query: str) -> str:
        query = query.strip()
        relation = None
        for source, target in RELATIONS.items():
            if query.startswith(source):
                relation = target.strip()
                query = query[len(source):]
                break
        for source, target in DESCRIPTORS.items():
            query = query.replace(source, target + " ")
        for source, target in sorted(ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
            query = query.replace(source, target)
        query = " ".join(query.split())
        return f"{query} {relation}".strip() if relation else query

    def _text(self, canonical: str):
        if canonical not in self.text_cache:
            prompt = canonical if canonical.lower().startswith("a ") else f"a {canonical}"
            self.text_cache[canonical] = self.predictor.encode_text([prompt])
        return self.text_cache[canonical], [canonical]

    @staticmethod
    def _postprocess(output, canonical: str, image_size=None, iou: float = 0.40, threshold: float = 0.06):
        import torch
        from torchvision.ops import nms
        scores = output.scores.detach()
        boxes = output.boxes.detach()
        if not len(scores):
            return []
        keep = nms(boxes, scores, iou)
        keep = keep[torch.argsort(scores[keep], descending=True)[:5]]
        result=[]
        frame_area=float(image_size[0]*image_size[1]) if image_size else None
        for i in keep:
            score=float(scores[i])
            if score < threshold: continue
            box=[float(x) for x in boxes[i]]
            if frame_area:
                x1,y1,x2,y2=box; w,h=image_size
                clipped=(max(0,min(w,x2))-max(0,min(w,x1)))* (max(0,min(h,y2))-max(0,min(h,y1)))
                # A low-confidence box covering almost the whole image is
                # usually a background match rather than the requested item.
                if clipped/frame_area>0.80 and score<0.40: continue
            result.append({"label": canonical, "score": round(score, 4),
                           "box": [round(float(x), 2) for x in box]})
        return result

    def locate(self, image, query, prefix):
        import cv2
        import numpy as np
        import torch
        from PIL import Image

        start = time.monotonic()
        canonical = self._canonical(query)
        with self.guard:
            self._ensure()
            text, prompts = self._text(canonical)
            pil_image = Image.open(image).convert("RGB")
            with torch.inference_mode():
                # Keep the predictor's candidate pool broad; the stricter
                # postprocess threshold below is what decides visible boxes.
                output = self.predictor.predict(
                    pil_image, prompts, text_encodings=text, threshold=0.0
                )
                torch.cuda.synchronize()
            detections = self._postprocess(output, canonical, image_size=pil_image.size)
            raw_scores = sorted((round(float(x), 4) for x in output.scores.detach().cpu().tolist()), reverse=True)[:8]
            marked = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)
            for detection in detections:
                x1, y1, x2, y2 = map(int, detection["box"])
                x1, y1 = max(0, x1), max(0, y1)
                x2, y2 = min(marked.shape[1] - 1, x2), min(marked.shape[0] - 1, y2)
                cv2.rectangle(marked, (x1, y1), (x2, y2), (0, 220, 120), 2)
                cv2.putText(marked, f"{canonical} {detection['score']:.2f}",
                            (x1, max(20, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX,
                            0.55, (0, 220, 120), 2, cv2.LINE_AA)
            prefix = pathlib.Path(prefix)
            prefix.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(prefix.with_suffix(".png")), marked)
            result = {
                "image": str(prefix.with_suffix(".png")),
                "prompt": prompts[0],
                "backend": "nanoowl-owlvit-base-patch32-tensorrt",
                "inference_seconds": round(time.monotonic() - start, 4),
                "top_scores": raw_scores,
                "detections": detections,
            }
            prefix.with_suffix(".json").write_text(
                json.dumps(result, ensure_ascii=False), encoding="utf-8"
            )
            self.last_used = time.monotonic()
            return result

    def unload(self):
        with self.guard:
            self.predictor = None
            self.text_cache.clear()
            try:
                import torch
                torch.cuda.empty_cache()
                ctypes.CDLL("libc.so.6").malloc_trim(0)
            except Exception:
                pass

    def loaded(self):
        return self.predictor is not None

    def reap(self):
        while True:
            time.sleep(5)
            if self.predictor is not None and time.monotonic() - self.last_used > self.idle_seconds:
                self.unload()
