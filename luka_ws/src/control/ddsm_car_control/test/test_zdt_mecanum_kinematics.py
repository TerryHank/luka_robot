import math

from ddsm_car_control.zdt_mecanum_kinematics import (
    MecanumGeometry,
    apply_lateral_hardware_direction,
    motor_delta_degrees_to_body_delta,
    scale_body_twist,
    twist_to_motor_rpm,
)


def test_forward_cmd_vel_maps_to_opposite_motor_signs_on_right_side():
    geometry = MecanumGeometry()

    rpm = twist_to_motor_rpm(0.12, 0.0, 0.0, geometry=geometry)

    assert rpm == {1: 23, 2: -23, 3: 23, 4: -23}


def test_left_strafe_cmd_vel_maps_to_mecanum_x_pattern():
    geometry = MecanumGeometry()

    rpm = twist_to_motor_rpm(0.0, 0.10, 0.0, geometry=geometry)

    assert rpm == {1: -19, 2: -19, 3: 19, 4: 19}


def test_body_twist_scaling_adjusts_lateral_and_turning_ratio():
    vx, vy, wz = scale_body_twist(
        0.30,
        0.20,
        0.40,
        forward_scale=1.0,
        lateral_scale=0.65,
        angular_scale=0.70,
    )

    assert vx == pytest_approx(0.30)
    assert vy == pytest_approx(0.13)
    assert wz == pytest_approx(0.28)


def test_motor_rpm_accepts_motion_ratio_scales():
    geometry = MecanumGeometry()

    rpm = twist_to_motor_rpm(
        0.0,
        0.10,
        0.40,
        geometry=geometry,
        lateral_scale=0.50,
        angular_scale=0.50,
    )

    assert rpm == twist_to_motor_rpm(
        0.0,
        0.05,
        0.20,
        geometry=geometry,
    )


def test_lateral_hardware_direction_flips_motor_mix_without_changing_ros_twist():
    vx, motor_vy, wz = apply_lateral_hardware_direction(
        0.0,
        0.08,
        0.0,
        lateral_direction=-1,
    )

    assert vx == pytest_approx(0.0)
    assert motor_vy == pytest_approx(-0.08)
    assert wz == pytest_approx(0.0)


def test_motor_deltas_integrate_forward_wheel_motion():
    geometry = MecanumGeometry()
    circumference = math.pi * geometry.wheel_diameter_m

    dx, dy, dyaw = motor_delta_degrees_to_body_delta(
        {1: 360.0, 2: -360.0, 3: 360.0, 4: -360.0},
        geometry,
    )

    assert dx == pytest_approx(circumference)
    assert dy == pytest_approx(0.0)
    assert dyaw == pytest_approx(0.0)


def test_motor_deltas_integrate_left_strafe_motion():
    geometry = MecanumGeometry()
    circumference = math.pi * geometry.wheel_diameter_m

    dx, dy, dyaw = motor_delta_degrees_to_body_delta(
        {1: -360.0, 2: -360.0, 3: 360.0, 4: 360.0},
        geometry,
    )

    assert dx == pytest_approx(0.0)
    assert dy == pytest_approx(circumference)
    assert dyaw == pytest_approx(0.0)


def test_motor_gear_ratio_scales_command_and_odometry_symmetrically():
    geometry = MecanumGeometry(motor_gear_ratio=2.0)

    rpm = twist_to_motor_rpm(0.12, 0.0, 0.0, geometry=geometry)
    dx, dy, dyaw = motor_delta_degrees_to_body_delta(
        {1: 720.0, 2: -720.0, 3: 720.0, 4: -720.0},
        geometry,
    )

    assert rpm == {1: 45, 2: -45, 3: 45, 4: -45}
    assert dx == pytest_approx(math.pi * geometry.wheel_diameter_m)
    assert dy == pytest_approx(0.0)
    assert dyaw == pytest_approx(0.0)


def pytest_approx(value):
    import pytest

    return pytest.approx(value, abs=1e-9)

def test_command_velocity_fallback_integrates_forward_odometry():
    from ddsm_car_control.zdt_mecanum_rs485_bridge import OdomEstimate, integrate_body_twist

    odom = OdomEstimate()
    integrate_body_twist(odom, vx=0.3, vy=0.0, wz=0.0, dt=2.0)

    assert odom.x == pytest_approx(0.6)
    assert odom.y == pytest_approx(0.0)
    assert odom.yaw == pytest_approx(0.0)
    assert odom.vx == pytest_approx(0.3)
    assert odom.vy == pytest_approx(0.0)
    assert odom.wz == pytest_approx(0.0)
    assert odom.seq == 1


def test_command_velocity_fallback_integrates_rotation():
    from ddsm_car_control.zdt_mecanum_rs485_bridge import OdomEstimate, integrate_body_twist

    odom = OdomEstimate()
    integrate_body_twist(odom, vx=0.0, vy=0.0, wz=0.5, dt=2.0)

    assert odom.x == pytest_approx(0.0)
    assert odom.y == pytest_approx(0.0)
    assert odom.yaw == pytest_approx(1.0)
    assert odom.wz == pytest_approx(0.5)
    assert odom.seq == 1
