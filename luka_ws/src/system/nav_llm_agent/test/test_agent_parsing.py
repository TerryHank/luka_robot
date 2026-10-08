from nav_llm_agent.agent_node import (
    extract_json,
    normalize_model_call,
    resolve_direct_navigation_command,
    resolve_grounded_waypoint,
    resolve_direct_volume_command,
    needs_voice_rephrase,
    sanitize_chat_answer,
    looks_like_robot_command,
    tool_is_grounded,
)
import pytest


def test_new_tool_call_schema():
    parsed = extract_json(
        '```json\n{"tool":"go_home","arguments":{}}\n```'
    )
    assert normalize_model_call(parsed)["tool"] == "go_home"


def test_old_intent_schema_remains_compatible():
    call = normalize_model_call(
        {"intent": "elevator", "floor": "floor_3"}
    )
    assert call == {
        "tool": "elevator_enter",
        "arguments": {"floor": "floor_3"},
    }


def test_cancel_intent_maps_to_unified_cancel():
    call = normalize_model_call({"intent": "cancel"})
    assert call == {"tool": "cancel_all", "arguments": {}}


def test_unknown_text_cannot_fall_back_to_internal_waypoint():
    waypoints = {
        "bathroom": {"aliases": ["厕所"], "internal": False},
        "wp_005": {"aliases": [], "internal": True},
    }
    with pytest.raises(ValueError):
        resolve_grounded_waypoint("wp_005", "据说", waypoints)


def test_spoken_alias_overrides_wrong_model_pick():
    waypoints = {
        "bathroom": {"aliases": ["厕所"], "internal": False},
        "wp_005": {"aliases": [], "internal": True},
    }
    assert resolve_grounded_waypoint("wp_005", "去厕所", waypoints) == "bathroom"


def test_ungrounded_motion_tool_is_rejected():
    assert not tool_is_grounded("go_home", "据说")
    assert tool_is_grounded("go_home", "回充电点")


def test_explicit_alias_navigation_bypasses_model():
    waypoints = {
        "bathroom": {"aliases": ["浴室", "卫生间", "厕所"]},
        "kitchen": {"aliases": ["厨房"]},
    }
    assert resolve_direct_navigation_command("去浴室", waypoints) == "bathroom"
    assert resolve_direct_navigation_command("请带我去卫生间", waypoints) == "bathroom"
    assert resolve_direct_navigation_command("你能带我去厨房吗", waypoints) == "kitchen"


def test_direct_navigation_rejects_cross_floor_negation_and_unknown_text():
    waypoints = {"bathroom": {"aliases": ["浴室", "厕所"]}}
    assert resolve_direct_navigation_command("去二楼厕所", waypoints) is None
    assert resolve_direct_navigation_command("不要去浴室", waypoints) is None
    assert resolve_direct_navigation_command("据说浴室很大", waypoints) is None


def test_chat_and_control_routing_are_separated():
    assert not looks_like_robot_command("今天天气怎么样")
    assert not looks_like_robot_command("给我讲个笑话")
    assert looks_like_robot_command("开始巡航")
    assert looks_like_robot_command("停止")
    assert looks_like_robot_command("去二楼厨房")
    assert looks_like_robot_command("你能带我去厨房吗")
    assert resolve_direct_volume_command("加大音量") == "volume_up"
    assert resolve_direct_volume_command("声音小一点") == "volume_down"


def test_short_asr_fragments_and_looping_chat_are_contained():
    assert needs_voice_rephrase("带子")
    assert needs_voice_rephrase("骗的")
    assert not needs_voice_rephrase("今天天气怎么样")
    assert sanitize_chat_answer("好的呀。呀，好的啦。") == "好的。"
