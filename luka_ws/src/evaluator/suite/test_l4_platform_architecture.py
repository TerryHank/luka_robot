from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_platform_manifest_has_all_requested_layers():
    text = read("system/nav_llm_agent/config/interaction_platform.yaml")
    for token in (
        "audio_frontend:",
        "voice_runtime:",
        "speech_backend:",
        "xiaozhi:",
        "agent_gateway:",
        "downstream: L3 Mission",
    ):
        assert token in text


def test_audio_frontend_has_real_guarded_and_webrtc_profiles():
    text = read("system/bringup/audio_frontend_env.sh")
    assert "guarded)" in text
    assert "pulse_webrtc)" in text
    assert "module-echo-cancel" in text
    assert "aec_method=webrtc" in text
    assert "noise_suppression=1" in text
    assert "NX_MIC=pulse" in text
    assert "NX_SPEAKER=pulse" in text


def test_voice_backends_use_unified_agent_ingress():
    base = read("system/nav_llm_agent/nav_llm_agent/voice_gateway.py")
    dr = read("system/nav_llm_agent/nav_llm_agent/voice_suite_bridge.py")
    nx = read("visualization/console/nx_voice_gateway.py")
    for text in (base, dr, nx):
        assert "/luka/interaction/agent_input" in text
    assert 'create_publisher(String, "/llm_command"' not in base
    assert 'create_publisher(String, "/llm_command"' not in dr


def test_agent_gateway_is_transport_only():
    text = read("system/nav_llm_agent/nav_llm_agent/interaction/agent_gateway.py")
    forbidden = (
        "geometry_msgs",
        "nav2_msgs",
        "NavigateToPose",
        "ActionClient",
        "cmd_vel",
        "ddsm",
        "/api/assistant/execute",
    )
    for token in forbidden:
        assert token not in text.lower() if token == "ddsm" else token not in text


def test_xiaozhi_mcp_uses_l4_tool_gateway_not_ros_motion():
    server = read("system/xiaozhi/luka_mcp_server.py")
    gateway = read("system/xiaozhi/luka_agent_gateway.py")
    assert "LukaAgentGateway" in server
    assert "gateway.execute_tool" in server
    for text in (server, gateway):
        assert "geometry_msgs" not in text
        assert "nav2_msgs" not in text
        assert "cmd_vel" not in text
        assert "DDSM" not in text


def test_xiaozhi_modes_prevent_dual_audio_ownership():
    text = read("system/scripts/start_xiaozhi_platform.sh")
    assert "mcp_only)" in text
    assert "exclusive_remote)" in text
    assert "nx_voice_gateway.py|voice_gateway|sensevoice_ros2" in text
    assert "Refusing exclusive_remote" in text


def test_agent_service_starts_gateway_status_and_l3_agent():
    text = read("system/bringup/start_nx_agent.sh")
    assert "interaction_gateway" in text
    assert "interaction_status" in text
    assert "agent_node" in text
    assert "wait -n" in text


def test_l4_python_has_no_direct_motion_authority():
    roots = [
        ROOT / "system/nav_llm_agent/nav_llm_agent/interaction",
        ROOT / "system/xiaozhi",
    ]
    forbidden = (
        "NavigateToPose",
        "geometry_msgs.msg import Twist",
        '"/cmd_vel"',
        "'/cmd_vel'",
        "ddsm_car_control",
    )
    for directory in roots:
        for path in directory.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            for token in forbidden:
                assert token not in text, f"{token} leaked into {path}"
