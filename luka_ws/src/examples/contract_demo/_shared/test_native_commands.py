"""Pure callback regression: no driver, velocity command or live goal."""
from concurrent.futures import Future
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import pytest
from geometry_msgs.msg import PoseStamped
from std_srvs.srv import Trigger

spec = importlib.util.spec_from_file_location("native_commands", Path(__file__).with_name("native_commands.py"))
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)


def future(value):
    f = Future()
    f.set_result(value)
    return f


def pose(frame="map"):
    p = PoseStamped()
    p.header.frame_id = frame
    p.pose.orientation.w = 1.
    return p


@pytest.fixture
def node():
    n = native.NativeCommands.__new__(native.NativeCommands)
    n.nav, n.gate = Mock(), Mock()
    n.pending, n.goal, n.goal_at, n.goal_handle, n.deadline, n.generation = False, None, 0., None, 0., 0
    n.state, n.map_state, n.map_busy = {}, {}, False
    n.nav.server_is_ready.return_value = True
    n.gate.service_is_ready.return_value = True
    n.gate.call_async.return_value = Future()
    n.get_clock = Mock(return_value=SimpleNamespace(now=lambda: SimpleNamespace(to_msg=lambda: pose().header.stamp)))
    return n


def test_drawing_stages_without_sending(node):
    node.stage(pose())
    assert node.state["state"] == "staged"
    node.nav.send_goal_async.assert_not_called()
    node.gate.call_async.assert_not_called()


@pytest.mark.parametrize("frame", ["odom", "base_link", ""])
def test_reject_wrong_frame(node, frame):
    node.stage(pose(frame))
    assert node.goal is None


def test_reject_nonfinite_and_bad_quaternion(node):
    p = pose(); p.pose.position.x = float("nan")
    node.stage(p); assert node.goal is None
    p = pose(); p.pose.orientation.w = 0.
    node.stage(p); assert node.goal is None


def test_expired_pose_does_not_call_gate(node):
    node.stage(pose()); node.goal_at -= 31
    assert not node.send(None, Trigger.Response()).success
    node.gate.call_async.assert_not_called()


def test_unavailable_action_rejects(node):
    node.stage(pose()); node.nav.server_is_ready.return_value = False
    assert not node.send(None, Trigger.Response()).success
    node.gate.call_async.assert_not_called()


def test_gate_rejection_never_sends_action(node):
    node.stage(pose())
    node.gate.call_async.return_value = future(SimpleNamespace(success=False, message="stale sensors"))
    node.send(None, Trigger.Response())
    assert node.state["state"] == "gate_rejected"
    node.nav.send_goal_async.assert_not_called()


def test_cancel_during_gate_check_blocks_late_enable(node):
    node.stage(pose()); f = Future(); node.gate.call_async.return_value = f
    node.send(None, Trigger.Response()); node.cancel(None, Trigger.Response())
    f.set_result(SimpleNamespace(success=True))
    node.nav.send_goal_async.assert_not_called()
    assert node.gate.call_async.call_args.args[0].data is False


def test_late_action_ack_is_cancelled(node):
    handle = Mock(accepted=True)
    node.generation = 2
    node.accepted(future(handle), 1)
    handle.cancel_goal_async.assert_called_once()
    assert node.goal_handle is None


def test_successful_action_result_and_feedback(node):
    node.stage(pose())
    handle = Mock(accepted=True)
    result = Future(); handle.get_result_async.return_value = result
    node.nav.send_goal_async.return_value = future(handle)
    node.gate.call_async.return_value = future(SimpleNamespace(success=True))
    node.send(None, Trigger.Response())
    assert node.state["state"] == "executing"
    node.feedback(SimpleNamespace(feedback=SimpleNamespace(distance_remaining=.4)))
    assert node.state["distance_remaining"] == .4
    result.set_result(SimpleNamespace(status=4))
    assert node.state["action_status"] == 4 and not node.pending
    assert node.gate.call_async.call_args.args[0].data is False


def test_ack_timeout_cancels(node):
    node.pending, node.deadline = True, native.time.monotonic()-1
    node.output, node.map_output = Mock(), Mock()
    node.tick()
    assert not node.pending and node.state["state"] == "cancel_requested"


def test_busy_map_refuses_duplicate_export(node):
    node.map_busy = True
    with patch.object(native.subprocess, "run") as run:
        assert not node.save_map(None, Trigger.Response()).success
        run.assert_not_called()
