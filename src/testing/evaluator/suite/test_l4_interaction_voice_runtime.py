from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "system/nav_llm_agent"))

from nav_llm_agent.interaction import (  # noqa: E402
    AudioFrontendPolicy,
    VoiceRuntime,
    VoiceState,
)


def test_reference_sources_are_pinned():
    text = (ROOT / "common/vendor/voice/REFERENCE_LOCK.md").read_text(
        encoding="utf-8")
    assert "0d576d3d4c049c6f55eaf879725dc23e516511b4" in text
    assert "4f3d8252373fdbbec7c20add928ff084aeff4066" in text
    assert "ade6cd1cc25ee105dc7d0fee600c56b8dd8b4305" in text


def test_default_frontend_is_guarded_half_duplex():
    policy = AudioFrontendPolicy.build()
    assert policy.duplex_mode.value == "guarded_half_duplex"
    assert policy.aec_provider == "none"
    assert not policy.capture_during_playback
    assert not policy.acoustic_barge_in


def test_full_duplex_is_impossible_without_explicit_aec_provider():
    with pytest.raises(ValueError):
        AudioFrontendPolicy.build(
            duplex_mode="aec_full_duplex",
            aec_provider="none",
        )


def test_xiaozhi_style_speaking_to_listening_transition():
    policy = AudioFrontendPolicy.build(
        duplex_mode="aec_full_duplex",
        aec_provider="validated_external_aec",
    )
    runtime = VoiceRuntime(policy, continuous_dialogue=True)
    runtime.ready()
    runtime.wake_detected("露卡")
    runtime.playback_started("wake_ack")
    assert runtime.state is VoiceState.SPEAKING
    assert runtime.manual_barge_in("vad")
    assert runtime.state is VoiceState.LISTENING


def test_l4_interaction_runtime_has_no_motion_authority():
    directory = ROOT / "system/nav_llm_agent/nav_llm_agent/interaction"
    text = "\n".join(
        p.read_text(encoding="utf-8")
        for p in directory.glob("*.py")
    )
    forbidden = (
        "from geometry_msgs",
        "import geometry_msgs",
        "NavigateToPose",
        "ActionClient(",
        "Twist(",
        '"/cmd_vel"',
        '"/navigate_to_pose"',
        "ddsm_car_control.",
    )
    for token in forbidden:
        assert token not in text


def test_actual_nx_pipeline_has_generation_safe_barge_in():
    text = (ROOT / "visualization/console/nx_tts_pipeline.py").read_text(
        encoding="utf-8")
    assert "capture_during_playback" in text
    assert "_tts_generation" in text
    assert "stale_playback_drained" in text
    assert "playback_started" in text
    assert "playback_drained" in text


def test_product_gateway_uses_vad_barge_in_without_dropping_cache():
    text = (ROOT / "visualization/console/nx_voice_gateway.py").read_text(
        encoding="utf-8")
    assert "_barge_in_from_speech('sherpa_vad')" in text
    assert "segment=self.speech_vad.feed(samples)" in text


def test_runtime_diagnostics_are_published():
    text = (
        ROOT / "system/nav_llm_agent/nav_llm_agent/voice_gateway.py"
    ).read_text(encoding="utf-8")
    assert '"/voice/runtime"' in text
    assert "AudioFrontendPolicy.build" in text
    assert "speech_barge_in" in text


def test_system_startup_stays_guarded_by_default():
    text = (ROOT / "system/bringup/start_nx_voice.sh").read_text(
        encoding="utf-8")
    assert 'LUKA_VOICE_DUPLEX_MODE="' + "$" + '{LUKA_VOICE_DUPLEX_MODE:-guarded_half_duplex}"' in text
    assert 'LUKA_VOICE_AEC_PROVIDER="' + "$" + '{LUKA_VOICE_AEC_PROVIDER:-none}"' in text


def test_drobotics_backend_uses_same_runtime_contract_without_claiming_aec():
    text = (
        ROOT / "system/nav_llm_agent/nav_llm_agent/voice_suite_bridge.py"
    ).read_text(encoding="utf-8")
    assert '"/voice/runtime"' in text
    assert 'duplex_mode="guarded_half_duplex"' in text
    assert 'aec_provider="none"' in text
    assert '"playback_timing"] = "estimated"' in text


def test_drobotics_backend_drops_asr_while_estimated_tts_is_speaking():
    text = (
        ROOT / "system/nav_llm_agent/nav_llm_agent/voice_suite_bridge.py"
    ).read_text(encoding="utf-8")
    assert "self.runtime.state is VoiceState.SPEAKING" in text
    assert "asr_ignored reason=playback_guard" in text
