import json
import math

import pytest

from ddsm_car_control.ddsm_udp_protocol import OdomFeedback, SentTwistPacket
from ddsm_car_control.udp_cmd_vel_bridge import (
    HeadingPID,
    HeadingPIDConfig,
    build_data_chain_payload,
    yaw_from_quaternion,
    shortest_angular_error,
)


def test_shortest_angular_error_wraps_across_pi():
    assert shortest_angular_error(-3.10, 3.10) == pytest.approx(0.083185, abs=1e-6)
    assert shortest_angular_error(3.10, -3.10) == pytest.approx(-0.083185, abs=1e-6)
    assert shortest_angular_error(0.25, 0.10) == pytest.approx(0.15, abs=1e-6)


def test_heading_pid_clamps_output_and_integral():
    pid = HeadingPID(
        HeadingPIDConfig(
            kp=10.0,
            ki=1.0,
            kd=0.0,
            max_wz=0.35,
            max_integral=0.05,
        )
    )

    assert pid.update(error=1.0, dt=0.1) == pytest.approx(0.35)
    assert pid.integral == pytest.approx(0.05)
    assert pid.update(error=-1.0, dt=0.1) == pytest.approx(-0.35)
    assert pid.integral == pytest.approx(-0.05)


def test_yaw_from_quaternion_extracts_imu_heading():
    yaw = math.radians(45.0)
    quat = type(
        "QuaternionLike",
        (),
        {
            "x": 0.0,
            "y": 0.0,
            "z": math.sin(yaw * 0.5),
            "w": math.cos(yaw * 0.5),
        },
    )()

    assert yaw_from_quaternion(quat) == pytest.approx(yaw)


def test_data_chain_payload_keeps_raw_cmd_vel_and_pid_corrected_udp_output():
    sent = SentTwistPacket(
        seq=9,
        stamp_ms=1234,
        vx=0.10,
        vy=0.0,
        wz=0.12,
        crc=0xA5,
        packet_hex="dummy",
        packet_len=21,
    )
    feedback = OdomFeedback(
        seq=10,
        stamp_ms=5678,
        x=0.0,
        y=0.0,
        yaw=0.2,
        vx=0.0,
        vy=0.0,
        wz=0.0,
        wheels=[],
    )

    payload = build_data_chain_payload(
        host="192.168.3.139",
        command_port=9001,
        command_source="cmd_vel",
        command_age_s=0.02,
        sent=sent,
        feedback=feedback,
        input_vx=0.10,
        input_vy=0.0,
        input_wz=0.0,
        heading_pid={
            "enabled": True,
            "active": True,
            "feedback_source": "imu",
            "target_yaw": 0.1,
            "current_yaw": 0.2,
            "error": -0.1,
            "correction_wz": 0.12,
        },
    )
    data = json.loads(payload)

    assert data["ros_cmd_vel_input"]["wz"] == 0.0
    assert data["bridge_udp_output"]["wz"] == pytest.approx(0.12)
    assert data["heading_pid"]["active"] is True
    assert data["heading_pid"]["feedback_source"] == "imu"
    assert data["heading_pid"]["error"] == pytest.approx(-0.1)
