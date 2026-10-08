from pathlib import Path

import rclpy

from ddsm_car_control.nav_lifecycle_autostarter import (
    LifecycleBatchSequence,
    NavigationAutostartGate,
    NavigationLifecycleAutostarter,
)


class Recorder:
    def __init__(self):
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return True


def test_gate_waits_for_localization_transform_before_starting_navigation():
    startup = Recorder()
    gate = NavigationAutostartGate(
        has_localization_transform=lambda: False,
        service_ready=lambda: True,
        send_startup=startup,
    )

    assert gate.tick() is False
    assert startup.calls == 0
    assert gate.started is False


def test_gate_starts_navigation_once_when_localization_transform_is_available():
    startup = Recorder()
    gate = NavigationAutostartGate(
        has_localization_transform=lambda: True,
        service_ready=lambda: True,
        send_startup=startup,
    )

    assert gate.tick() is True
    assert gate.tick() is True
    assert startup.calls == 1
    assert gate.started is True


def test_gate_retries_until_lifecycle_service_is_ready():
    startup = Recorder()
    ready_states = iter([False, True])
    gate = NavigationAutostartGate(
        has_localization_transform=lambda: True,
        service_ready=lambda: next(ready_states),
        send_startup=startup,
    )

    assert gate.tick() is False
    assert gate.tick() is True
    assert startup.calls == 1


def test_lifecycle_batch_sequence_advances_only_after_each_batch_succeeds():
    sequence = LifecycleBatchSequence(["/core/manage_nodes", "/safety/manage_nodes"])

    assert sequence.current_service == "/core/manage_nodes"
    assert sequence.completed is False
    assert sequence.advance() is False
    assert sequence.current_service == "/safety/manage_nodes"
    assert sequence.advance() is True
    assert sequence.completed is True


def test_manager_services_parameter_has_a_nonempty_string_array_default():
    source = Path(
        __import__("ddsm_car_control.nav_lifecycle_autostarter", fromlist=["__file__"]).__file__
    ).read_text(encoding="utf-8")

    assert 'declare_parameter("manager_services", [default_manager_service])' in source


def test_navigation_lifecycle_autostarter_node_can_be_constructed():
    rclpy.init()
    node = None
    try:
        node = NavigationLifecycleAutostarter()
        assert node.sequence.current_service == "/lifecycle_manager_navigation/manage_nodes"
    finally:
        if node is not None:
            node.destroy_node()
        rclpy.shutdown()
