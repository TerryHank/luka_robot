"""Mocked startup/stop tests never invoke ROS or a real service."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("contract_runner", Path(__file__).with_name("runner.py"))
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def result(code=0, stdout=""):
    return SimpleNamespace(returncode=code, stdout=stdout, stderr="")


def test_manifest_has_all_contract_clauses_once():
    assert len(runner.ITEMS) == 27
    assert len({i["clause"] for i in runner.ITEMS.values()}) == 27
    assert [i["number"] for i in runner.ITEMS.values()] == [f"{i:02d}" for i in range(1, 28)]
    assert runner.MANIFEST["payment"]["per_function_amounts"] is None


def test_missing_function_has_no_service_plan():
    with patch.object(runner, "active", return_value=False):
        assert runner.units_for(runner.ITEMS["16"]["profile"]) == []
        assert runner.units_for(runner.ITEMS["21"]["profile"]) == []


def test_localization_reuses_existing_odometry_owner():
    with patch.object(runner, "active", side_effect=lambda u: u == runner.LOCALIZATION):
        units = runner.units_for("navigation")
        assert runner.ODOM not in units and runner.LOC not in units
    with patch.object(runner, "active", return_value=False):
        assert runner.ODOM not in runner.units_for("navigation", ["/nx_readonly_wheel_odom"])


def test_slam_refuses_an_existing_map_owner():
    with patch.object(runner, "run", return_value=result()), \
            patch.object(runner, "active", side_effect=lambda u: u == runner.LOC):
        try:
            runner.guard("slam", [runner.SLAM], [])
        except RuntimeError as error:
            assert "地图" in str(error)
        else:
            raise AssertionError("SLAM duplicated map ownership")


def test_static_map_refuses_slam():
    with patch.object(runner, "run", return_value=result()), \
            patch.object(runner, "active", return_value=False):
        try:
            runner.guard("map", [runner.LOC], ["/slam_toolbox"])
        except RuntimeError as error:
            assert "SLAM" in str(error)
        else:
            raise AssertionError("Static map started alongside SLAM")


def test_stop_keeps_shared_and_preexisting_units(tmp_path):
    state = {"demos": {"03": [runner.SENSORS], "04": [runner.SENSORS]},
             "managed": [runner.SENSORS, runner.EKF]}
    with patch.object(runner, "STATE_DIR", tmp_path), \
            patch.object(runner, "run", return_value=result()) as call:
        runner.release("03", state)
        assert runner.SENSORS in state["managed"]
        assert runner.EKF not in state["managed"]
        assert all(runner.SENSORS not in c.args[0] for c in call.call_args_list)
        assert all(runner.BRIDGE not in c.args[0] for c in call.call_args_list)
        persisted = json.loads((tmp_path / "launcher_state.json").read_text())
        assert "04" in persisted["demos"]


def test_failed_stop_stays_tracked(tmp_path):
    state = {"demos": {"09": [runner.SLAM]}, "managed": [runner.SLAM]}
    with patch.object(runner, "STATE_DIR", tmp_path), \
            patch.object(runner, "run", return_value=result(1)):
        try:
            runner.release("09", state)
        except RuntimeError:
            assert runner.SLAM in state["managed"]
        else:
            raise AssertionError("Failed stop was treated as successful")


def test_start_only_owns_new_units(tmp_path):
    active_units = {runner.BRIDGE}

    def execute(argv, **kwargs):
        if argv[:4] == ["sudo", "-n", "systemctl", "start"]:
            active_units.add(argv[4])
        return result(stdout="stamp:\n  sec: 1\nframe_id: camera_color_optical_frame")

    with patch.object(runner, "STATE_DIR", tmp_path), \
            patch.object(runner, "units_for", return_value=[runner.BRIDGE, runner.SENSORS]), \
            patch.object(runner, "ros_nodes", return_value=set()), \
            patch.object(runner, "guard"), patch.object(runner, "install_aux"), \
            patch.object(runner, "status"), \
            patch.object(runner, "active", side_effect=lambda u: u in active_units), \
            patch.object(runner, "run", side_effect=execute) as call:
        runner.start(runner.ITEMS["05"])
        state = json.loads((tmp_path / "launcher_state.json").read_text())
        assert state["managed"] == [runner.SENSORS]
        assert runner.BRIDGE in state["demos"]["05"]
        assert all(c.args[0] != ["sudo", "-n", "systemctl", "start", runner.BRIDGE]
                   for c in call.call_args_list)


def test_planned_localization_blocks_concurrent_slam(tmp_path):
    with patch.object(runner, "STATE_DIR", tmp_path):
        runner.write_state({"demos": {"10": [runner.LOC]}, "managed": []})
        with patch.object(runner, "units_for", return_value=[runner.SLAM]), \
                patch.object(runner, "ros_nodes", return_value=set()), \
                patch.object(runner, "run") as call:
            try:
                runner.start(runner.ITEMS["09"])
            except RuntimeError as error:
                assert "仍引用" in str(error)
            else:
                raise AssertionError("Concurrent map owners were admitted")
            call.assert_not_called()
