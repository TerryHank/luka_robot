from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum


class DuplexMode(str, Enum):
    GUARDED_HALF_DUPLEX = "guarded_half_duplex"
    AEC_FULL_DUPLEX = "aec_full_duplex"


@dataclass(frozen=True)
class AudioFrontendPolicy:
    """Capabilities of the audio presented to Luka's voice runtime.

    ESP-Skainet is a design reference here: AEC/NS/KWS/VAD are modeled as an
    acoustic-front-end contract rather than being hardwired into the session
    state machine.  On S100 the actual engines remain replaceable.
    """

    profile: str = "guarded"
    duplex_mode: DuplexMode = DuplexMode.GUARDED_HALF_DUPLEX
    aec_provider: str = "none"
    ns_provider: str = "none"
    kws_engine: str = "sherpa_onnx"
    vad_engine: str = "sherpa_onnx"
    noise_suppression: bool = False
    pre_roll_ms: int = 600
    barge_in_enabled: bool = True

    @classmethod
    def build(
        cls,
        profile: str = "guarded",
        duplex_mode: str = DuplexMode.GUARDED_HALF_DUPLEX.value,
        aec_provider: str = "none",
        ns_provider: str = "none",
        kws_engine: str = "sherpa_onnx",
        vad_engine: str = "sherpa_onnx",
        noise_suppression: bool = False,
        pre_roll_ms: int = 600,
        barge_in_enabled: bool = True,
    ) -> "AudioFrontendPolicy":
        mode = DuplexMode(str(duplex_mode).strip().lower())
        profile_name = str(profile or "guarded").strip().lower()
        if profile_name not in {"guarded", "pulse_webrtc", "external_aec"}:
            raise ValueError(f"unsupported audio frontend profile: {profile_name}")
        provider = str(aec_provider or "none").strip().lower()
        ns = str(ns_provider or "none").strip().lower()
        if mode is DuplexMode.AEC_FULL_DUPLEX and provider in {
            "",
            "none",
            "disabled",
            "guarded",
        }:
            raise ValueError(
                "aec_full_duplex requires a named, externally validated "
                "echo-cancellation provider"
            )
        pre_roll = int(pre_roll_ms)
        if not 100 <= pre_roll <= 3000:
            raise ValueError("pre_roll_ms must be within 100..3000")
        if bool(noise_suppression) and ns in {"", "none", "disabled"}:
            raise ValueError(
                "noise_suppression=true requires a named NS provider"
            )
        return cls(
            profile=profile_name,
            duplex_mode=mode,
            aec_provider=provider,
            ns_provider=ns,
            kws_engine=str(kws_engine or "unknown"),
            vad_engine=str(vad_engine or "unknown"),
            noise_suppression=bool(noise_suppression),
            pre_roll_ms=pre_roll,
            barge_in_enabled=bool(barge_in_enabled),
        )

    @property
    def aec_ready(self) -> bool:
        return self.duplex_mode is DuplexMode.AEC_FULL_DUPLEX

    @property
    def capture_during_playback(self) -> bool:
        return self.aec_ready and self.barge_in_enabled

    @property
    def acoustic_barge_in(self) -> bool:
        return self.capture_during_playback

    def snapshot(self) -> dict:
        data = asdict(self)
        data["duplex_mode"] = self.duplex_mode.value
        data["aec_ready"] = self.aec_ready
        data["capture_during_playback"] = self.capture_during_playback
        return data
