import math

import pytest

from hotel_semantic_map.models import Poi
from hotel_semantic_map.named_navigation_server import (
    classify_final_status,
    covariance_is_ready,
    infer_final_approach,
    parse_topic_command,
)


def make_poi(profile: str) -> Poi:
    return Poi(
        id="room_801_door",
        display_name="Room 801",
        poi_type="guest_room",
        floor_id="floor_1",
        area_id="room_801_zone",
        x=1.0,
        y=2.0,
        yaw=0.0,
        final_approach_profile=profile,
        enabled=True,
        map_version="v1",
    )


def test_plain_topic_command_uses_destination_id():
    command = parse_topic_command(" room_801_door ")

    assert command.destination_id == "room_801_door"
    assert command.use_final_approach is None
    assert command.map_version == ""


def test_json_topic_command_supports_explicit_options():
    command = parse_topic_command(
        '{"destination_id":"room_801_door","use_final_approach":false,"map_version":"v1"}'
    )

    assert command.destination_id == "room_801_door"
    assert command.use_final_approach is False
    assert command.map_version == "v1"


def test_foxglove_string_message_json_data_field_is_accepted():
    command = parse_topic_command('{"data":"room_801_door"}')

    assert command.destination_id == "room_801_door"
    assert command.use_final_approach is None
    assert command.map_version == ""


@pytest.mark.parametrize(
    "value",
    ["", "{}", '{"destination_id":"room","use_final_approach":"yes"}'],
)
def test_invalid_topic_commands_are_rejected(value):
    with pytest.raises(ValueError):
        parse_topic_command(value)


def test_final_approach_is_inferred_from_profile():
    assert infer_final_approach(make_poi("doorway"))
    assert not infer_final_approach(make_poi("none"))
    assert not infer_final_approach(make_poi("disabled"))


def test_covariance_readiness_uses_xy_and_yaw_standard_deviation():
    covariance = [0.0] * 36
    covariance[0] = 0.20**2
    covariance[7] = 0.24**2
    covariance[35] = 0.29**2

    assert covariance_is_ready(
        covariance, xy_std_threshold=0.25, yaw_std_threshold=0.30
    )
    covariance[35] = 0.31**2
    assert not covariance_is_ready(
        covariance, xy_std_threshold=0.25, yaw_std_threshold=0.30
    )
    covariance[35] = math.nan
    assert not covariance_is_ready(
        covariance, xy_std_threshold=0.25, yaw_std_threshold=0.30
    )


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("navigating_to_staging", "pending"),
        ("final_servo", "pending"),
        ("final_reached", "success"),
        ("blocked_front:0.21", "failure"),
        ("staging_failed:6", "failure"),
        ("final_servo_timeout", "failure"),
        ("cancelled", "failure"),
    ],
)
def test_final_status_classification(status, expected):
    assert classify_final_status(status) == expected
