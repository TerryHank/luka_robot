from nav_llm_agent.interaction.agent_gateway import normalize_envelope


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
    from nav_llm_agent.interaction.agent_gateway import InteractionAgentGateway
    env = normalize_envelope('{"text":"你好","source":"voice_local"}')
    node = InteractionAgentGateway.__new__(InteractionAgentGateway)
    key = InteractionAgentGateway._dedup_key(node, env)
    assert key.endswith(":你好")
