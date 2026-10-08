import math

from ddsm_car_control.lateral_escape_guard import (
    adaptive_lateral_authority,
    forward_facing_velocity,
    normalize_motion_mode,
)


def convert(vx, vy, wz=0.0):
    return forward_facing_velocity(
        vx,
        vy,
        wz,
        heading_kp=2.0,
        max_wz=0.9,
        lateral_ratio=0.10,
        lateral_max=0.05,
    )


def test_forward_command_stays_forward_without_lateral_velocity():
    vx, vy, wz = convert(0.4, 0.0)
    assert vx == 0.4
    assert vy == 0.0
    assert wz == 0.0


def test_diagonal_command_keeps_moving_while_heading_catches_up():
    vx, vy, wz = convert(0.4, 0.4)
    assert vx == 0.4
    assert 0.0 < vy <= 0.05
    assert wz == 0.9


def test_small_heading_error_allows_small_bounded_sideways_motion():
    vx, vy, wz = convert(0.4, 0.04)
    assert vx == 0.4
    assert math.isclose(vy, 0.004)
    assert 0.0 < wz < 0.9


def test_reverse_request_turns_vehicle_around_instead_of_reversing():
    vx, vy, wz = convert(-0.3, 0.0)
    assert vx == 0.0
    assert vy == 0.0
    assert abs(wz) == 0.9


def test_lateral_authority_increases_smoothly_near_obstacle():
    kwargs = dict(
        trigger_distance=0.58,
        release_distance=1.20,
        normal_ratio=0.10,
        obstacle_ratio=0.85,
        normal_max=0.05,
        obstacle_max=0.22,
    )
    clear = adaptive_lateral_authority(None, **kwargs)
    middle = adaptive_lateral_authority(0.89, **kwargs)
    close = adaptive_lateral_authority(0.50, **kwargs)
    assert clear == (0.10, 0.05)
    assert clear[0] < middle[0] < close[0]
    assert clear[1] < middle[1] < close[1]
    assert math.isclose(close[0], 0.85)
    assert math.isclose(close[1], 0.22)


def test_motion_mode_aliases_are_normalized_safely():
    assert normalize_motion_mode('forward') == 'forward_facing'
    assert normalize_motion_mode('heading') == 'forward_facing'
    assert normalize_motion_mode('anything-else') == 'omni'
