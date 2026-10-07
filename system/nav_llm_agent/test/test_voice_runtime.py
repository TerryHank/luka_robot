import pytest

from nav_llm_agent.interaction import (
    AudioFrontendPolicy,
    DuplexMode,
    VoiceRuntime,
    VoiceState,
)


def guarded():
    return AudioFrontendPolicy.build()


def full_duplex():
    return AudioFrontendPolicy.build(
        duplex_mode="aec_full_duplex",
        aec_provider="webrtc_external",
    )


def test_guarded_profile_never_claims_acoustic_barge_in():
    policy = guarded()
    assert policy.duplex_mode is DuplexMode.GUARDED_HALF_DUPLEX
    assert not policy.aec_ready
    assert not policy.capture_during_playback
    assert not policy.acoustic_barge_in


def test_full_duplex_requires_named_aec_provider():
    with pytest.raises(ValueError):
        AudioFrontendPolicy.build(
            duplex_mode="aec_full_duplex",
            aec_provider="none",
        )


def test_xiaozhi_style_speaking_to_listening_requires_aec_for_wake():
    runtime = VoiceRuntime(guarded())
    runtime.ready()
    assert runtime.wake_detected("露卡")
    runtime.playback_started("wake_ack")
    assert runtime.state is VoiceState.SPEAKING
    assert not runtime.wake_detected("露卡", during_playback=True)
    assert runtime.state is VoiceState.SPEAKING

    runtime = VoiceRuntime(full_duplex())
    runtime.ready()
    assert runtime.wake_detected("露卡")
    runtime.playback_started("wake_ack")
    assert runtime.wake_detected("露卡", during_playback=True)
    assert runtime.state is VoiceState.LISTENING


def test_wake_ack_returns_to_listening():
    runtime = VoiceRuntime(guarded())
    runtime.ready()
    runtime.wake_detected("露卡")
    runtime.playback_started("wake_ack")
    runtime.playback_drained("wake_ack")
    assert runtime.state is VoiceState.LISTENING
    assert runtime.session_active


def test_one_shot_response_returns_idle():
    runtime = VoiceRuntime(guarded(), continuous_dialogue=False)
    runtime.ready()
    runtime.wake_detected("露卡")
    runtime.utterance_final("你好")
    runtime.playback_started("response")
    runtime.playback_drained("response")
    assert runtime.state is VoiceState.IDLE
    assert not runtime.session_active


def test_continuous_response_returns_listening():
    runtime = VoiceRuntime(guarded(), continuous_dialogue=True)
    runtime.ready()
    runtime.wake_detected("露卡")
    runtime.utterance_final("你好")
    runtime.playback_started("response")
    runtime.playback_drained("response")
    assert runtime.state is VoiceState.LISTENING
    assert runtime.session_active


def test_stale_playback_drained_does_not_cancel_barge_in():
    runtime = VoiceRuntime(full_duplex(), continuous_dialogue=True)
    runtime.ready()
    runtime.wake_detected("露卡")
    runtime.playback_started("wake_ack")
    runtime.wake_detected("露卡", during_playback=True)
    assert runtime.state is VoiceState.LISTENING
    runtime.playback_drained("wake_ack")
    assert runtime.state is VoiceState.LISTENING


def test_manual_barge_in_is_transport_safe_without_aec():
    runtime = VoiceRuntime(guarded())
    runtime.ready()
    runtime.playback_started("notification")
    assert runtime.manual_barge_in("ui_interrupt")
    assert runtime.state is VoiceState.LISTENING
