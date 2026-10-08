"""GUI management regressions; mock subprocess/services, no hardware starts."""
import importlib.util
from pathlib import Path
import threading
from types import SimpleNamespace as NS
from unittest.mock import Mock,patch
import pytest
from std_srvs.srv import Trigger,SetBool

spec=importlib.util.spec_from_file_location('follow_gui',Path(__file__).parents[1]/'scripts/gui_manager.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


def manager():
    n=module.GuiManager.__new__(module.GuiManager)
    n.lock=threading.Lock();n.epoch=0;n.process=None;n.live_verified=False;n.last_error=''
    n.follow,n.base_follow,n.base_nav=Mock(),Mock(),Mock()
    n.read_mode=Mock(return_value='dry_run')
    n.call=Mock(return_value=NS(success=True,message='ok'))
    return n


def test_observation_refuses_non_dry_mode():
    n=manager();n.read_mode.return_value='nav2_action'
    with pytest.raises(RuntimeError):n.enable_observation()
    n.call.assert_not_called()


def test_observation_uses_existing_setbool_only():
    n=manager();n.enable_observation()
    assert n.call.call_args.args[0] is n.follow and n.call.call_args.args[1].data is True


def test_stop_available_while_another_operation_holds_lock():
    n=manager();n.lock.acquire()
    reply=n.stop_handler(None,Trigger.Response())
    assert reply.success and n.epoch==1
    assert len(n.call.call_args_list)==3
    assert all(call.args[1].data is False for call in n.call.call_args_list)


def test_stop_attempts_all_gates_despite_first_failure():
    n=manager();n.call.side_effect=[RuntimeError('timeout'),NS(success=True),NS(success=True)]
    reply=n.stop_handler(None,Trigger.Response())
    assert not reply.success and len(n.call.call_args_list)==3
    assert n.live_verified is False


def test_late_operation_cannot_override_stop():
    n=manager()
    def operation():n.epoch+=1;return 'late completion'
    reply=n.handler(operation)(None,Trigger.Response())
    assert not reply.success and n.epoch==2


@pytest.mark.parametrize('ack,ready',[(False,True),(True,False)])
def test_action_mode_requires_operator_and_production_interfaces(ack,ready):
    n=manager();n.production_ready=Mock(return_value=ready);n.start=Mock();n.close_preview=Mock()
    reply=n.prepare_action_mode(SetBool.Request(data=ack),SetBool.Response())
    assert not reply.success;n.start.assert_not_called();n.close_preview.assert_not_called()


def test_existing_dry_kernel_is_reused_without_another_process():
    n=manager();assert '复用' in n.start('dry_run')


def test_other_mode_kernel_is_not_replaced():
    n=manager();n.read_mode.return_value='nav2_action'
    with pytest.raises(RuntimeError):n.start('dry_run')


def test_no_velocity_publisher_in_gui_source():
    import ast
    tree=ast.parse(Path(__file__).parents[1]/'scripts/gui_manager.py'.read_text())
    assert all('Twist' not in ast.get_source_segment(Path(__file__).parents[1]/'scripts/gui_manager.py'.read_text(),n)
               for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='create_publisher')
