"""GUI launch policy and parameter tests; no real hardware process is started."""
import importlib.util
from pathlib import Path
import signal
import threading
from types import SimpleNamespace
from unittest.mock import Mock, patch
import pytest
from rclpy.parameter import Parameter

spec=importlib.util.spec_from_file_location("gui_launcher",Path(__file__).with_name("gui_launcher.py"))
gui=importlib.util.module_from_spec(spec);spec.loader.exec_module(gui)


@pytest.fixture
def engine(tmp_path):
    return gui.CaseEngine({"03":{"profile":"imu_launch","launch":True},
                           "06":{"profile":"environment"},
                           "10":{"profile":"map","launch":True,"launch_group":"map"},
                           "16":{"profile":"missing","limitation":"not implemented"}},data=tmp_path)


def test_invalid_and_missing_do_not_spawn(engine):
    with patch.object(gui.subprocess,"Popen") as spawn:
        for number in ("99","16","01;touch /tmp/bad"):
            with pytest.raises(ValueError):engine.start(number)
        spawn.assert_not_called()


def test_requires_stopping_previous_case(engine):
    engine.children=[("03",Mock(),Path("unused"))]
    with pytest.raises(RuntimeError,match="停止"):engine.start("06")


def test_path_validation_and_no_spawn_before_bad_map(engine,tmp_path):
    outside=tmp_path/"outside.yaml";outside.write_text("data")
    with patch.object(gui.subprocess,"Popen") as spawn:
        with pytest.raises(ValueError):engine.start("10",map_yaml=str(outside))
        spawn.assert_not_called()
    valid=tmp_path/"maps/map.yaml";valid.parent.mkdir();valid.write_text("data")
    assert engine.validate_map(str(valid))==valid


def test_spawn_is_fixed_argv_and_no_reverse_ssh_dependency(engine):
    proc=Mock(pid=123,poll=Mock(return_value=None))
    with patch.object(gui.subprocess,"Popen",return_value=proc) as spawn:
        engine.start("06")
    args,kwargs=spawn.call_args
    assert args[0][-2:]==["--item","06"] and kwargs["start_new_session"]
    assert kwargs["env"]["FOXGLOVE_GUI_LAUNCH"]=="1"
    assert "shell" not in kwargs


def test_stop_only_own_children_in_reverse_order(engine,tmp_path):
    calls=[]
    def child(name):
        p=Mock();p.poll.return_value=None;p.send_signal.side_effect=lambda s:calls.append((name,s));return p
    engine.children=[("base",child("base"),tmp_path/"a"),("slam",child("slam"),tmp_path/"b")]
    engine.stop()
    assert calls==[("slam",signal.SIGINT),("base",signal.SIGINT)]
    assert engine.children==[] and engine.phase=="idle"


def test_timeout_does_not_forget_live_owner(engine,tmp_path):
    p=Mock();p.poll.return_value=None;p.wait.side_effect=gui.subprocess.TimeoutExpired("launch",25)
    engine.children=[("03",p,tmp_path/"log")]
    with pytest.raises(gui.subprocess.TimeoutExpired):engine.stop()
    assert len(engine.children)==1


def test_stop_during_start_prevents_later_spawn(engine):
    engine.cancel_start.set()
    with patch.object(gui.subprocess,"Popen") as spawn:
        with pytest.raises(InterruptedError):engine.start_process("06")
        spawn.assert_not_called()


def test_unknown_parameter_is_rejected(engine):
    node=gui.GuiLauncher.__new__(gui.GuiLauncher);node.engine=engine
    response=node.parameters([Parameter("shell_command",value="anything")])
    assert not response.successful


def test_missing_item_gui_returns_failure(engine):
    node=gui.GuiLauncher.__new__(gui.GuiLauncher);node.engine=engine
    response=node.start("16",False,SimpleNamespace())
    assert not response.success


def test_busy_stop_is_queued_not_ignored(engine):
    node=gui.GuiLauncher.__new__(gui.GuiLauncher);node.engine=engine;node.busy=True
    assert node.stop(None,SimpleNamespace()).success
    assert engine.cancel_start.is_set()


def test_async_failure_is_visible_without_false_success(engine):
    node=gui.GuiLauncher.__new__(gui.GuiLauncher);node.engine=engine;node.busy=False
    def fail():raise RuntimeError("source missing")
    response=node.submit(fail,SimpleNamespace())
    node.worker.join()
    assert response.success and not node.busy and engine.phase=="error"
    assert "source missing" in engine.message
