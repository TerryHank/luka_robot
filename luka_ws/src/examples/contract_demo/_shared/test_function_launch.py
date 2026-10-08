"""Regression tests for real launch plans and read-only live output."""
import importlib.util
from pathlib import Path
from unittest.mock import patch
import pytest
from launch import LaunchContext
from launch.actions import ExecuteProcess, IncludeLaunchDescription
from launch_ros.actions import Node
from sensor_msgs.msg import LaserScan, Image
from nav_msgs.msg import Path as RosPath
from nav2_msgs.msg import CollisionMonitorState

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("function_launch",HERE/"function_demo.launch.py")
demo=importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)
spec=importlib.util.spec_from_file_location("function_readout",HERE/"function_readout.py")
readout=importlib.util.module_from_spec(spec)
spec.loader.exec_module(readout)


def context(profile, hardware=True):
    c=LaunchContext()
    c.launch_configurations.update(profile=profile,start_hardware=str(hardware).lower(),
                                   map_yaml=str(demo.WS.parent/"luka_data/maps/ddsm_map_floor_4.yaml"))
    return c


def plan(profile, graph=(), hardware=True):
    with patch.object(demo,"claim",return_value=lambda *a:None), \
         patch.object(demo,"active",return_value=False), \
         patch.object(demo,"nodes",return_value=set(graph)), \
         patch.object(demo,"port_free"),patch.object(demo,"reserve_device"):
        return demo.setup(context(profile,hardware))


@pytest.mark.parametrize("profile",demo.PROFILES)
def test_isolated_launch_has_only_readout_process(profile):
    actions=plan(profile,hardware=False)
    processes=[a for a in actions if isinstance(a,ExecuteProcess)]
    assert len(processes)==1
    assert not any(isinstance(a,(Node,IncludeLaunchDescription)) for a in actions)


@pytest.mark.parametrize("profile,graph,reason",[
    ("slam",["/amcl"],"map/TF"),
    ("navigation",["/slam_toolbox"],"Stop SLAM"),
    ("navigation",["/nx_readonly_wheel_odom"],"protected base"),
    ("lidar",["/nx_imu"],"Partial sensor"),
    ("navigation",["/controller_server"],"Partial Nav2"),
    ("business",["/ddsm_home_manager"],"Partial business"),
    ("map",["/amcl"],"Partial localization"),
    ("lidar",["/nx_readonly_wheel_odom","/zdt_mecanum_rs485_bridge"],"Multiple base"),
])
def test_duplicate_or_incompatible_owners_are_rejected(profile,graph,reason):
    with pytest.raises(RuntimeError,match=reason):
        plan(profile,graph)


def test_lidar_reports_actual_valid_ranges():
    m=LaserScan(range_min=.1,range_max=10.,ranges=[float("nan"),float("inf"),.01,.5,2.])
    assert readout.describe(m)=="rays=5 valid=2 nearest=0.500 m"


def test_depth_reports_units_and_invalid_pixels():
    m=Image(height=1,width=1,encoding="16UC1",step=2,data=[0xe8,0x03])
    assert "center_depth=1.000 m" in readout.describe(m)
    m.data=[0,0]
    assert "INVALID" in readout.describe(m)


def test_path_and_collision_have_correct_message_types():
    assert "waypoints=0" in readout.describe(RosPath())
    assert "action_type=1 polygon=stop"==readout.describe(CollisionMonitorState(action_type=1,polygon_name="stop"))


def test_all_runnable_items_use_ros_launch():
    import json
    items=json.loads((HERE.parent/"manifest.json").read_text())["items"]
    for item in items:
        if "launch" in item:
            folder=HERE.parent/item["folder"]
            assert (folder/"demo.launch.py").is_file()
            assert 'exec ros2 launch "$HERE/demo.launch.py"' in (folder/"demo.sh").read_text()
            assert (folder/"stop.sh").is_file()

def test_device_startup_reservation_prevents_races(tmp_path):
    import interactive_support as support
    import fcntl
    with patch.object(support,"STATE",tmp_path):
        support.reserve_device("test_port")
        lock=support.LOCKS.pop()
        try:
            with pytest.raises(RuntimeError,match="another demonstration"):
                support.reserve_device("test_port")
        finally:
            lock.close()


def test_foreground_stop_does_not_stop_systemd_services():
    text=(HERE/"stop_launch.py").read_text()
    assert "systemctl" not in text
    assert "start_ticks" in text and "launch_token" in text
    assert "os.kill(pid, signal.SIGINT)" in text


def test_custom_map_outside_data_root_is_rejected():
    c=context("map",False)
    c.launch_configurations["map_yaml"]="/etc/unsafe.yaml"
    with patch.object(demo,"claim",return_value=lambda *a:None):
        with pytest.raises(RuntimeError,match="inside luka_data/maps"):
            demo.setup(c)


def test_nonexistent_custom_map_is_rejected_before_hardware_start():
    c=context("map",True)
    c.launch_configurations["map_yaml"]=str(demo.WS.parent/"luka_data/maps/no_such_acceptance_map.yaml")
    with patch.object(demo,"claim",return_value=lambda *a:None),patch.object(demo,"nodes",return_value=set()):
        with pytest.raises(RuntimeError,match="existing YAML"):
            demo.setup(c)
