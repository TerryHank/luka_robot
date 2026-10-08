import pytest
from pathlib import Path

from ddsm_car_control.ddsm_mission_control import (
    MissionRecord,
    dump_mission_record,
    load_mission_record,
    parse_navigation_status_state,
    parse_control_command,
    should_reject_new_goal,
)


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ("pause", "pause"),
        (" resume ", "resume"),
        ("cancel", "cancel"),
        ('{"data":"pause"}', "pause"),
        ('{"command":"resume"}', "resume"),
        ('{"action":"cancel"}', "cancel"),
    ],
)
def test_parse_control_command_accepts_raw_and_json(payload, expected):
    assert parse_control_command(payload) == expected


@pytest.mark.parametrize("payload", ["", "stop", "{}", '{"data":"stop"}', "[]"])
def test_parse_control_command_rejects_invalid_payloads(payload):
    with pytest.raises(ValueError):
        parse_control_command(payload)


def test_dump_and_load_mission_record_round_trip(tmp_path):
    path = tmp_path / "mission_state.yaml"
    record = MissionRecord(
        state="paused",
        task_type="named_destination",
        target_id="wp_003",
        display_name="门口",
        route_id="",
        waypoint_index=0,
        use_final_approach=True,
    )

    dump_mission_record(path, record)
    loaded = load_mission_record(path)

    assert loaded == record


def test_load_missing_mission_record_returns_idle(tmp_path):
    loaded = load_mission_record(tmp_path / "missing.yaml")

    assert loaded.state == "idle"
    assert loaded.task_type == ""
    assert loaded.target_id == ""


def test_should_reject_new_goal_only_when_paused():
    assert should_reject_new_goal("paused") is True
    assert should_reject_new_goal("running") is False
    assert should_reject_new_goal("idle") is False
    assert should_reject_new_goal("canceled") is False


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ('{"state":"succeeded","destination_id":"wp_002"}', "succeeded"),
        ('{"state":"cancelled","destination_id":"wp_002"}', "canceled"),
        ('{"state":"failed","destination_id":"wp_002"}', "failed"),
        ('{"failure_code":"CANCELLED","destination_id":"wp_002"}', "canceled"),
    ],
)
def test_parse_navigation_status_state_recognizes_terminal_results(payload, expected):
    assert parse_navigation_status_state(payload) == expected


@pytest.mark.parametrize(
    "payload",
    [
        "",
        "running",
        '{"state":"navigating","destination_id":"wp_002"}',
        '{"state":"accepted","destination_id":"wp_002"}',
        '{"message":"arrived"}',
    ],
)
def test_parse_navigation_status_state_ignores_non_terminal_results(payload):
    assert parse_navigation_status_state(payload) is None


def test_mission_control_keeps_subscription_handles():
    source = (
        Path(__file__).resolve().parents[1]
        / "ddsm_car_control"
        / "ddsm_mission_control.py"
    ).read_text()

    for handle_name in (
        "pause_sub",
        "resume_sub",
        "cancel_sub",
        "control_sub",
        "goal_seen_sub",
        "navigation_status_sub",
    ):
        assert f"self.{handle_name} = self.create_subscription" in source


def test_mission_status_latches_only_latest_state():
    source = (
        Path(__file__).resolve().parents[1]
        / "ddsm_car_control"
        / "ddsm_mission_control.py"
    ).read_text()

    assert "QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)" in source


def test_mission_control_separates_public_and_internal_goal_topics():
    source = (
        Path(__file__).resolve().parents[1]
        / "ddsm_car_control"
        / "ddsm_mission_control.py"
    ).read_text()

    assert 'self.declare_parameter("goal_request_topic", "/hotel/goal_destination")' in source
    assert 'self.declare_parameter("hotel_goal_topic", "/hotel/mission/goal_destination")' in source
    assert 'str(self.get_parameter("goal_request_topic").value)' in source


def test_mission_control_exposes_fast_service_controls():
    source = (
        Path(__file__).resolve().parents[1]
        / "ddsm_car_control"
        / "ddsm_mission_control.py"
    ).read_text()

    for service_name in ("pause_now", "resume_now", "cancel_now"):
        assert f'"/hotel/mission/{service_name}"' in source
    assert "self.pause_srv = self.create_service" in source
    assert "self.resume_srv = self.create_service" in source
    assert "self.cancel_srv = self.create_service" in source
