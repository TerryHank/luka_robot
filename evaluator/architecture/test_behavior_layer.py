import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'behavior/luka_behaviors'))
from luka_behaviors.navigate import NavigateBehavior
from luka_behaviors.stop import StopBehavior
from luka_behaviors.registry import BehaviorRegistry


def test_navigation_adapter_preserves_arguments_and_cancellation():
    send=Mock(return_value={'ok':True});cancel=Mock()
    behavior=NavigateBehavior(send,cancel,lambda:{'active':False})
    assert behavior.start('kitchen',observation={'x':1})=={'ok':True}
    send.assert_called_once_with('kitchen',observation={'x':1})
    behavior.cancel(wait_for_gate=False)
    cancel.assert_called_once_with(wait_for_gate=False)


def test_stop_attempts_all_behaviors_when_one_cancellation_fails():
    follow=Mock();follow.cancel.side_effect=RuntimeError('gate unavailable')
    nav=Mock();relocalize=Mock();mission=Mock()
    stop=StopBehavior(SimpleNamespace(follow=follow,navigate=nav,relocalize=relocalize),lambda:mission)
    assert not stop.start()['ok']
    mission.stop.assert_called_once();nav.cancel.assert_called_once();relocalize.cancel.assert_called_once()


def test_ros_watchdog_never_blocks_its_callback_group_waiting_for_gate_response():
    registry=BehaviorRegistry.__new__(BehaviorRegistry)
    registry.node=SimpleNamespace(nx_handle=object(),motion=SimpleNamespace(valid=lambda _:False,desired=None))
    registry.navigate=Mock();registry.follow=None
    registry.relocalize=SimpleNamespace(legacy_controller=SimpleNamespace(running=False))
    registry.motion_watchdog()
    registry.navigate.cancel.assert_called_once_with(wait_for_gate=False)
