import math
from dataclasses import dataclass
from typing import Dict, Iterable


def clamp(value: float, lower: float, upper: float) -> float:
    return min(max(value, lower), upper)


def lround(value: float) -> int:
    if value >= 0.0:
        return int(math.floor(value + 0.5))
    return int(math.ceil(value - 0.5))


@dataclass(frozen=True)
class MecanumGeometry:
    wheel_diameter_m: float = 0.1016
    wheel_base_m: float = 0.310
    track_width_m: float = 0.355
    motor_gear_ratio: float = 1.0

    @property
    def wheel_radius_m(self) -> float:
        return self.wheel_diameter_m * 0.5

    @property
    def wheel_circumference_m(self) -> float:
        return math.pi * self.wheel_diameter_m

    @property
    def rotation_arm_m(self) -> float:
        return 0.5 * (self.wheel_base_m + self.track_width_m)


DEFAULT_MOTOR_DIRECTIONS = {
    1: 1,   # front left after reversing the chassis heading
    2: -1,  # front right after reversing the chassis heading
    3: 1,   # rear left after reversing the chassis heading
    4: -1,  # rear right after reversing the chassis heading
}


def normalize_motor_directions(directions: Dict[int, int] | None) -> Dict[int, int]:
    values = dict(DEFAULT_MOTOR_DIRECTIONS if directions is None else directions)
    missing = {1, 2, 3, 4} - set(values)
    if missing:
        raise ValueError(f"missing motor directions for ids: {sorted(missing)}")
    return {motor_id: 1 if values[motor_id] >= 0 else -1 for motor_id in (1, 2, 3, 4)}


def clamp_planar_velocity(
    vx: float,
    vy: float,
    max_linear_speed: float,
) -> tuple[float, float]:
    if max_linear_speed <= 0.0:
        return vx, vy
    speed = math.hypot(vx, vy)
    if speed <= max_linear_speed or speed == 0.0:
        return vx, vy
    scale = max_linear_speed / speed
    return vx * scale, vy * scale


def scale_body_twist(
    vx: float,
    vy: float,
    wz: float,
    forward_scale: float = 1.0,
    lateral_scale: float = 1.0,
    angular_scale: float = 1.0,
) -> tuple[float, float, float]:
    return (
        float(vx) * max(float(forward_scale), 0.0),
        float(vy) * max(float(lateral_scale), 0.0),
        float(wz) * max(float(angular_scale), 0.0),
    )


def apply_lateral_hardware_direction(
    vx: float,
    vy: float,
    wz: float,
    lateral_direction: float = 1.0,
) -> tuple[float, float, float]:
    direction = -1.0 if float(lateral_direction) < 0.0 else 1.0
    return float(vx), float(vy) * direction, float(wz)


def twist_to_physical_wheel_rpm(
    vx: float,
    vy: float,
    wz: float,
    geometry: MecanumGeometry,
) -> Dict[int, float]:
    arm = geometry.rotation_arm_m
    rpm_factor = 60.0 / geometry.wheel_circumference_m
    wheel_linear = {
        1: vx - vy - arm * wz,
        2: vx + vy + arm * wz,
        3: vx + vy - arm * wz,
        4: vx - vy + arm * wz,
    }
    return {motor_id: speed * rpm_factor for motor_id, speed in wheel_linear.items()}


def twist_to_motor_rpm(
    vx: float,
    vy: float,
    wz: float,
    geometry: MecanumGeometry | None = None,
    motor_directions: Dict[int, int] | None = None,
    max_rpm: float = 300.0,
    deadband: float = 1e-4,
    forward_scale: float = 1.0,
    lateral_scale: float = 1.0,
    angular_scale: float = 1.0,
) -> Dict[int, int]:
    geometry = geometry or MecanumGeometry()
    directions = normalize_motor_directions(motor_directions)
    vx, vy, wz = scale_body_twist(
        vx,
        vy,
        wz,
        forward_scale=forward_scale,
        lateral_scale=lateral_scale,
        angular_scale=angular_scale,
    )
    if abs(vx) < deadband and abs(vy) < deadband and abs(wz) < deadband:
        return {motor_id: 0 for motor_id in (1, 2, 3, 4)}

    physical_rpm = twist_to_physical_wheel_rpm(vx, vy, wz, geometry)
    return {
        motor_id: lround(
            clamp(
                physical_rpm[motor_id]
                * geometry.motor_gear_ratio
                * directions[motor_id],
                -max_rpm,
                max_rpm,
            )
        )
        for motor_id in (1, 2, 3, 4)
    }


def motor_delta_degrees_to_body_delta(
    motor_delta_degrees: Dict[int, float],
    geometry: MecanumGeometry,
    motor_directions: Dict[int, int] | None = None,
) -> tuple[float, float, float]:
    directions = normalize_motor_directions(motor_directions)

    distances = {}
    for motor_id in (1, 2, 3, 4):
        motor_degrees = float(motor_delta_degrees.get(motor_id, 0.0))
        physical_degrees = (
            motor_degrees * directions[motor_id] / geometry.motor_gear_ratio
        )
        distances[motor_id] = physical_degrees / 360.0 * geometry.wheel_circumference_m

    d1, d2, d3, d4 = (distances[i] for i in (1, 2, 3, 4))
    dx = (d1 + d2 + d3 + d4) * 0.25
    dy = (-d1 + d2 + d3 - d4) * 0.25
    dyaw = (-d1 + d2 - d3 + d4) / (4.0 * geometry.rotation_arm_m)
    return dx, dy, dyaw


def physical_wheel_rpm_to_body_twist(
    wheel_rpm: Dict[int, float],
    geometry: MecanumGeometry,
) -> tuple[float, float, float]:
    meters_per_minute = {
        motor_id: float(wheel_rpm.get(motor_id, 0.0)) * geometry.wheel_circumference_m
        for motor_id in (1, 2, 3, 4)
    }
    v1, v2, v3, v4 = (meters_per_minute[i] / 60.0 for i in (1, 2, 3, 4))
    vx = (v1 + v2 + v3 + v4) * 0.25
    vy = (-v1 + v2 + v3 - v4) * 0.25
    wz = (-v1 + v2 - v3 + v4) / (4.0 * geometry.rotation_arm_m)
    return vx, vy, wz


def unwrap_degrees(previous: float, current: float, period_degrees: float = 360.0) -> float:
    half = period_degrees * 0.5
    return (current - previous + half) % period_degrees - half


def mean_abs(values: Iterable[float]) -> float:
    values = list(values)
    if not values:
        return 0.0
    return sum(abs(value) for value in values) / len(values)
