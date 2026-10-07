from nav_llm_agent.interaction.envelope import (
    dedup_key,
    normalize_envelope,
    public_envelope,
)


def test_plain_text_is_normalized():
    env = normalize_envelope("你好", "voice_local")
    assert env["schema"] == "luka.interaction.text.v1"
    assert env["source"] == "voice_local"
    assert env["text"] == "你好"
    assert env["turn_id"]


def test_json_envelope_preserves_speaker():
    env = normalize_envelope(
        '{"text":"带我去厨房","source":"voice_local","speaker":{"state":"known"}}'
    )
    assert env["speaker"]["state"] == "known"
    assert env["source"] == "voice_local"


def test_unknown_source_is_rejected():
    try:
        normalize_envelope('{"text":"x","source":"motor_controller"}')
    except ValueError as exc:
        assert "unsupported interaction source" in str(exc)
    else:
        raise AssertionError("unknown source must fail closed")


def test_missing_turn_id_uses_content_for_transport_dedup():
    env = normalize_envelope('{"text":"你好","source":"voice_local"}')
    assert dedup_key(env).endswith(":你好")


def test_explicit_turn_id_is_idempotency_key():
    env = normalize_envelope(
        '{"text":"你好","source":"app","session_id":"s1","turn_id":"t1"}'
    )
    assert dedup_key(env) == "app:s1:t1"


def test_private_normalization_marker_never_leaves_gateway():
    env = public_envelope(normalize_envelope("你好", "voice_local"))
    assert "_provided_turn_id" not in env
