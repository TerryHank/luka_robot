import importlib
import sys
from types import ModuleType


class FakeNode:
    pass


class FakeState:
    PRIMARY_STATE_UNKNOWN = 0
    PRIMARY_STATE_UNCONFIGURED = 1
    PRIMARY_STATE_INACTIVE = 2
    PRIMARY_STATE_ACTIVE = 3
    PRIMARY_STATE_FINALIZED = 4
    TRANSITION_STATE_CONFIGURING = 10
    TRANSITION_STATE_ACTIVATING = 13


class FakeTransition:
    TRANSITION_CONFIGURE = 1
    TRANSITION_ACTIVATE = 3


class FakeChangeState:
    class Request:
        pass


class FakeGetState:
    class Request:
        pass


def import_autostarter_with_ros_stubs(monkeypatch):
    rclpy = ModuleType("rclpy")
    rclpy.init = lambda args=None: None
    rclpy.spin = lambda node: None
    rclpy.shutdown = lambda: None

    rclpy_node = ModuleType("rclpy.node")
    rclpy_node.Node = FakeNode

    lifecycle_msgs = ModuleType("lifecycle_msgs")
    lifecycle_msgs_msg = ModuleType("lifecycle_msgs.msg")
    lifecycle_msgs_msg.State = FakeState
    lifecycle_msgs_msg.Transition = FakeTransition
    lifecycle_msgs_srv = ModuleType("lifecycle_msgs.srv")
    lifecycle_msgs_srv.ChangeState = FakeChangeState
    lifecycle_msgs_srv.GetState = FakeGetState

    monkeypatch.setitem(sys.modules, "rclpy", rclpy)
    monkeypatch.setitem(sys.modules, "rclpy.node", rclpy_node)
    monkeypatch.setitem(sys.modules, "lifecycle_msgs", lifecycle_msgs)
    monkeypatch.setitem(sys.modules, "lifecycle_msgs.msg", lifecycle_msgs_msg)
    monkeypatch.setitem(sys.modules, "lifecycle_msgs.srv", lifecycle_msgs_srv)
    sys.modules.pop("ddsm_car_control.slam_lifecycle_autostarter", None)

    return importlib.import_module("ddsm_car_control.slam_lifecycle_autostarter")


def test_startup_transition_configures_unconfigured_slam_toolbox(monkeypatch):
    autostarter = import_autostarter_with_ros_stubs(monkeypatch)

    assert (
        autostarter.startup_transition_for_state(FakeState.PRIMARY_STATE_UNCONFIGURED)
        == FakeTransition.TRANSITION_CONFIGURE
    )


def test_startup_transition_activates_inactive_slam_toolbox(monkeypatch):
    autostarter = import_autostarter_with_ros_stubs(monkeypatch)

    assert (
        autostarter.startup_transition_for_state(FakeState.PRIMARY_STATE_INACTIVE)
        == FakeTransition.TRANSITION_ACTIVATE
    )


def test_startup_transition_leaves_active_or_transitional_states_alone(monkeypatch):
    autostarter = import_autostarter_with_ros_stubs(monkeypatch)

    assert autostarter.startup_transition_for_state(FakeState.PRIMARY_STATE_ACTIVE) is None
    assert (
        autostarter.startup_transition_for_state(FakeState.TRANSITION_STATE_CONFIGURING)
        is None
    )
    assert (
        autostarter.startup_transition_for_state(FakeState.TRANSITION_STATE_ACTIVATING)
        is None
    )


def test_normalize_target_node_adds_leading_slash(monkeypatch):
    autostarter = import_autostarter_with_ros_stubs(monkeypatch)

    assert autostarter.normalize_target_node("slam_toolbox") == "/slam_toolbox"
    assert autostarter.normalize_target_node("/slam_toolbox") == "/slam_toolbox"


def test_pending_request_timeout_uses_elapsed_seconds(monkeypatch):
    autostarter = import_autostarter_with_ros_stubs(monkeypatch)

    assert autostarter.pending_request_timed_out(10.0, 14.9, 5.0) is False
    assert autostarter.pending_request_timed_out(10.0, 15.0, 5.0) is True
    assert autostarter.pending_request_timed_out(None, 15.0, 5.0) is False
