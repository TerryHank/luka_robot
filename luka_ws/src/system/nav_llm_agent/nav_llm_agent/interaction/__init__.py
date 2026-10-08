"""L4 Interaction runtime primitives.

The package borrows architecture ideas from xiaozhi-esp32 and ESP-Skainet but
contains no ESP32/ESP-SR runtime code.
"""

from .audio_frontend import AudioFrontendPolicy, DuplexMode
from .voice_runtime import VoiceRuntime, VoiceState, VoiceStateMachine
from .envelope import dedup_key, normalize_envelope, public_envelope
from .speech_backends import (
    LocalSenseVoiceASR,
    LocalTTSBackend,
    SpeechBackendProfile,
    get_profile,
)

__all__ = [
    "AudioFrontendPolicy",
    "DuplexMode",
    "VoiceRuntime",
    "VoiceState",
    "VoiceStateMachine",
    "LocalSenseVoiceASR",
    "LocalTTSBackend",
    "SpeechBackendProfile",
    "get_profile",
    "dedup_key",
    "normalize_envelope",
    "public_envelope",
]
