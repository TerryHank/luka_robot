import json

from ddsm_car_control.ddsm_udp_protocol import OdomFeedback, SentTwistPacket, WheelFeedback
from ddsm_car_control.udp_cmd_vel_bridge import (
    build_data_chain_payload,
    compute_expected_wheel_targets,
    limit_linear_velocity,
    select_velocity_command,
)


def test_compute_expected_wheel_targets_matches_firmware_layout():
    targets = compute_expected_wheel_targets(0.12, 0.0)

    assert targets == [
        {"id": 1, "target_rpm": 30},
        {"id": 2, "target_rpm": -30},
        {"id": 3, "target_rpm": 30},
        {"id": 4, "target_rpm": -30},
    ]


def test_build_data_chain_payload_includes_command_packet_and_wheel_feedback():
    sent = SentTwistPacket(
        seq=4,
        stamp_ms=123,
        vx=0.12,
        vy=0.0,
        wz=0.0,
        crc=0x5A,
        packet_hex="c2dd04007b0000008fc2f53d00000000000000005a",
        packet_len=21,
    )
    feedback = OdomFeedback(
        seq=8,
        stamp_ms=456,
        x=1.0,
        y=2.0,
        yaw=0.3,
        vx=0.11,
        vy=0.0,
        wz=0.01,
        wheels=[
            WheelFeedback(
                wheel_id=1,
                valid=True,
                mode=2,
                torque=3,
                speed_rpm=29,
                position=1000,
                total_encoder=123456,
                error=0,
                age_ms=4,
            )
        ],
    )

    payload = build_data_chain_payload(
        host="192.168.3.139",
        command_port=9001,
        command_source="cmd_vel",
        command_age_s=0.02,
        sent=sent,
        feedback=feedback,
    )
    data = json.loads(payload)

    assert data["ros_cmd_vel_input"]["vx"] == 0.12
    assert data["bridge_udp_output"]["seq"] == 4
    assert data["esp32_inverse_kinematics_expected"]["wheel_targets_rpm"][1]["target_rpm"] == -30
    assert data["motor_feedback_input"]["wheels"][0]["speed_rpm"] == 29
    assert data["motor_feedback_input"]["wheels"][0]["total_encoder"] == 123456
    assert data["esp32_odometry_method"]["source"] == "DDSM315 pos"
    assert data["ros_odom_output"]["x"] == 1.0
    assert data["ros_tf_output"]["parent_frame_id"] == "odom"
    assert data["ros_tf_output"]["child_frame_id"] == "base_link"


def test_select_velocity_command_uses_nav_when_manual_is_absent():
    selected = select_velocity_command(
        manual_cmd=None,
        manual_age_s=0.0,
        nav_cmd="nav",
        nav_age_s=0.05,
        manual_timeout_s=0.4,
        nav_timeout_s=0.4,
    )

    assert selected.command == "nav"
    assert selected.source == "cmd_vel_nav"
    assert selected.age_s == 0.05


def test_select_velocity_command_prefers_recent_manual_over_nav():
    selected = select_velocity_command(
        manual_cmd="manual",
        manual_age_s=0.10,
        nav_cmd="nav",
        nav_age_s=0.02,
        manual_timeout_s=0.4,
        nav_timeout_s=0.4,
    )

    assert selected.command == "manual"
    assert selected.source == "cmd_vel"
    assert selected.age_s == 0.10


def test_limit_linear_velocity_clamps_mapping_speed_to_configured_limit():
    assert limit_linear_velocity(0.5, 0.0, 0.3) == (0.3, 0.0)
    assert limit_linear_velocity(-0.5, 0.0, 0.3) == (-0.3, 0.0)
    assert limit_linear_velocity(0.1, 0.0, 0.3) == (0.1, 0.0)
    assert limit_linear_velocity(0.5, 0.0, 0.0) == (0.5, 0.0)
