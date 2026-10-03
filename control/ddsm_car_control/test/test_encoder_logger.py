import json

from ddsm_car_control.encoder_logger import (
    extract_encoder_snapshot,
    format_encoder_snapshot,
)


def test_extract_encoder_snapshot_reads_wheel_positions_from_data_chain():
    payload = {
        "esp32_odom_udp_input": {
            "seq": 8,
            "stamp_ms": 456,
        },
        "motor_feedback_input": {
            "wheels": [
                {
                    "id": 1,
                    "valid": True,
                    "mode": 2,
                    "torque": 3,
                    "speed_rpm": 29,
                    "position": 1000,
                    "total_encoder": -4_294_967_300,
                    "error": 0,
                    "age_ms": 4,
                },
                {
                    "id": 3,
                    "valid": True,
                    "mode": 2,
                    "torque": -1,
                    "speed_rpm": 0,
                    "position": 14705,
                    "error": 0,
                    "age_ms": 6,
                },
            ]
        },
    }

    snapshot = extract_encoder_snapshot(json.dumps(payload))

    assert snapshot["seq"] == 8
    assert snapshot["stamp_ms"] == 456
    assert snapshot["wheels"][0]["id"] == 1
    assert snapshot["wheels"][0]["position"] == 1000
    assert snapshot["wheels"][0]["total_encoder"] == -4_294_967_300
    assert snapshot["wheels"][1]["id"] == 3
    assert snapshot["wheels"][1]["position"] == 14705
    assert snapshot["wheels"][1]["total_encoder"] is None


def test_format_encoder_snapshot_prints_compact_encoder_summary():
    snapshot = {
        "seq": 8,
        "stamp_ms": 456,
        "wheels": [
            {
                "id": 3,
                "valid": True,
                "mode": 2,
                "torque": -1,
                "speed_rpm": 0,
                "position": 14705,
                "total_encoder": -12345678901,
                "error": 0,
                "age_ms": 6,
            }
        ],
    }

    text = format_encoder_snapshot(snapshot)

    assert text == (
        "encoder snapshot seq=8 stamp_ms=456 | "
        "wheel3 pos=14705 total=-12345678901 rpm=0 torque=-1 "
        "mode=2 err=0 age=6ms valid=True"
    )
