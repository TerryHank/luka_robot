import pytest

from ddsm_car_control.ddsm_udp_protocol import OdomFeedback
from ddsm_car_control.udp_cmd_vel_bridge import build_odom_transform


def test_build_odom_transform_uses_odom_pose_and_frames():
    feedback = OdomFeedback(
        seq=1,
        stamp_ms=100,
        x=1.25,
        y=-0.5,
        yaw=0.3,
        vx=0.0,
        vy=0.0,
        wz=0.0,
        wheels=[],
    )

    transform = build_odom_transform(
        feedback=feedback,
        stamp=None,
        odom_frame_id="odom",
        base_frame_id="base_link",
    )

    assert transform.header.frame_id == "odom"
    assert transform.child_frame_id == "base_link"
    assert transform.transform.translation.x == 1.25
    assert transform.transform.translation.y == -0.5
    assert transform.transform.translation.z == 0.0
    assert transform.transform.rotation.z == pytest.approx(0.149438, abs=1e-6)
    assert transform.transform.rotation.w == pytest.approx(0.988771, abs=1e-6)
