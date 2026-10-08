"""Load S100 offline voice models without requiring microphone or speaker."""

from pathlib import Path
from glob import glob
import time
import sys

import sherpa_onnx

ROOT = Path("/home/sunrise/luka_ws")
MODELS = ROOT / "common/models/voice"
sys.path.insert(0, str(ROOT / "system/runtime/tools"))
from nx_tts_backend import create_tts


def first(pattern):
    paths = glob(str(pattern))
    if len(paths) != 1:
        raise RuntimeError(f"Expected one file for {pattern}, got {paths}")
    return paths[0]


start = time.monotonic()
kws_dir = MODELS / "sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01-mobile"
kws = sherpa_onnx.KeywordSpotter(
    tokens=str(kws_dir / "tokens.txt"),
    encoder=first(kws_dir / "encoder*.int8.onnx"),
    decoder=first(kws_dir / "decoder*.onnx"),
    joiner=first(kws_dir / "joiner*.int8.onnx"),
    keywords_file=str(MODELS / "keywords.txt"),
    num_threads=2, keywords_score=2.5, max_active_paths=8,
    keywords_threshold=0.08, provider="cpu",
)
print("kws_loaded_s", round(time.monotonic() - start, 2), flush=True)
asr_dir = MODELS / "sensevoice"
asr = sherpa_onnx.OfflineRecognizer.from_sense_voice(
    tokens=str(asr_dir / "tokens.txt"), model=str(asr_dir / "model.int8.onnx"),
    num_threads=4, sample_rate=16000, language="zh", use_itn=True,
    provider="cpu",
)
print("asr_loaded_s", round(time.monotonic() - start, 2), flush=True)
tts = create_tts("matcha", str(MODELS / "matcha-icefall-zh-baker"), 2)
audio = tts.generate("你好，我是露卡。", sid=0, speed=1.3)
print("tts_generated_s", round(time.monotonic() - start, 2),
      "samples", len(audio.samples), flush=True)
