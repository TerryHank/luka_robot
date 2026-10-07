from __future__ import annotations

from dataclasses import asdict, dataclass
import os
import re

import numpy as np


SENSEVOICE_TAG_RE = re.compile(r"<\|[^|]+\|>")


@dataclass(frozen=True)
class SpeechBackendProfile:
    name: str
    asr: str
    tts: str
    transport: str
    owns_capture: bool
    owns_playback: bool
    playback_feedback: str

    def snapshot(self) -> dict:
        return asdict(self)


PROFILES = {
    "luka_local": SpeechBackendProfile(
        name="luka_local",
        asr="sherpa_onnx_sensevoice",
        tts="sherpa_onnx_local",
        transport="in_process",
        owns_capture=False,
        owns_playback=False,
        playback_feedback="exact",
    ),
    "drobotics": SpeechBackendProfile(
        name="drobotics",
        asr="sensevoice_ros2",
        tts="hobot_tts",
        transport="ros2_topics",
        owns_capture=True,
        owns_playback=True,
        playback_feedback="estimated",
    ),
    "xiaozhi_remote": SpeechBackendProfile(
        name="xiaozhi_remote",
        asr="xiaozhi_server",
        tts="xiaozhi_server",
        transport="mqtt_udp_opus",
        owns_capture=True,
        owns_playback=True,
        playback_feedback="remote_protocol",
    ),
}


def get_profile(name: str) -> SpeechBackendProfile:
    key = str(name or "").strip().lower()
    if key not in PROFILES:
        raise ValueError(f"unsupported speech backend profile: {key}")
    return PROFILES[key]


class LocalSenseVoiceASR:
    """In-process SenseVoice adapter used by the existing Luka voice path."""

    name = "sherpa_onnx_sensevoice"

    def __init__(self, model_dir: str, sample_rate: int = 16000, threads: int = 4):
        import sherpa_onnx

        model_dir = os.path.abspath(model_dir)
        self.sample_rate = int(sample_rate)
        self.recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            tokens=os.path.join(model_dir, "tokens.txt"),
            model=os.path.join(model_dir, "model.int8.onnx"),
            num_threads=max(1, int(threads)),
            sample_rate=self.sample_rate,
            language="zh",
            use_itn=True,
            provider="cpu",
        )

    def transcribe(self, samples, sample_rate: int | None = None) -> str:
        rate = int(sample_rate or self.sample_rate)
        audio = np.asarray(samples, dtype=np.float32)
        if audio.ndim != 1 or not audio.size:
            return ""
        if rate != self.sample_rate:
            raise ValueError(
                f"ASR sample rate mismatch: expected {self.sample_rate}, got {rate}"
            )
        stream = self.recognizer.create_stream()
        stream.accept_waveform(rate, audio)
        self.recognizer.decode_stream(stream)
        return SENSEVOICE_TAG_RE.sub("", stream.result.text or "").strip()


class LocalTTSBackend:
    """Thin adapter around the existing sherpa-onnx TTS object."""

    name = "sherpa_onnx_local"

    def __init__(self, engine):
        self.engine = engine

    @property
    def num_speakers(self):
        return self.engine.num_speakers

    def generate(self, *args, **kwargs):
        return self.engine.generate(*args, **kwargs)
