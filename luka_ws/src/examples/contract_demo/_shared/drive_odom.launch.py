"""One measured-odometry and protected keyboard-control demonstration."""
from pathlib import Path
import sys
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, OpaqueFunction, RegisterEventHandler, EmitEvent
from launch.event_handlers import OnProcessExit, OnShutdown
from launch.events import Shutdown
from launch.substitutions import LaunchConfiguration

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from interactive_support import WS, SRC, active, nodes, tty_path, keyboard_command, enabled, claim, reserve_device


def setup(context):
    hardware = enabled(LaunchConfiguration("start_hardware").perform(context))
    keyboard = enabled(LaunchConfiguration("keyboard").perform(context))
    terminal = tty_path() if keyboard else None
    clear = claim("drive_odom", HERE / "drive_odom.launch.py")
    actions = [RegisterEventHandler(OnShutdown(on_shutdown=clear))]
    graph = nodes()
    if keyboard:
        import re
        import subprocess
        p = subprocess.run(["ros2", "topic", "info", "/nx/web_teleop_cmd_vel"],
                           capture_output=True, text=True, timeout=10)
        publishers = re.search(r"Publisher count:\s*(\d+)", p.stdout)
        if publishers and int(publishers.group(1)) > 0:
            raise RuntimeError("Manual input already has a publisher; stop that controller first.")
    if hardware:
        if active("luka-contract-odom.service") or "/nx_readonly_wheel_odom" in graph:
            raise RuntimeError("Read-only odometry owns the base. Stop its demo before keyboard driving.")
        if not active("luka-ws-hardware@manual_base.service"):
            if "/zdt_mecanum_rs485_bridge" in graph:
                raise RuntimeError("Unmanaged base driver already running; refuse a second serial owner.")
            reserve_device("base_port")
            p = __import__("subprocess").run(["fuser", "/dev/nx_base"], capture_output=True)
            if p.returncode == 0:
                raise RuntimeError("Base serial port is occupied; no second driver will be started.")
            actions.append(ExecuteProcess(
                cmd=["python3", str(SRC / "visualization/console/nx_manual_base.py"),
                     "--ros-args", "--params-file", str(SRC / "common/config/nx_manual_base.yaml"),
                     "-r", "odom:=/wheel/odom"], output="screen",
                additional_env={"PYTHONUNBUFFERED": "1"}))
        if not active("luka-ws-hardware@sensors.service"):
            if any(n in graph for n in ("/nx_imu", "/nx_upper_lidar", "/nx_lower_lidar")):
                raise RuntimeError("Unmanaged sensors already running; reuse their official service first.")
            reserve_device("imu_port")
            actions.append(ExecuteProcess(
                cmd=["ros2", "launch", str(SRC / "system/bringup/nx_sensors.launch.py")],
                output="screen"))
    actions.append(ExecuteProcess(
        cmd=["python3", str(HERE / "telemetry_readout.py"), "--mode", "odom"],
        output="screen", additional_env={"PYTHONUNBUFFERED": "1"}))
    if keyboard:
        # The original terminal is reopened explicitly because launch child stdin is a pipe.
        key = ExecuteProcess(cmd=keyboard_command(terminal), output="screen", emulate_tty=True)
        actions += [key, RegisterEventHandler(OnProcessExit(
            target_action=key, on_exit=[EmitEvent(event=Shutdown(reason="keyboard exited"))]))]
    return actions


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument("start_hardware", default_value="true"),
        DeclareLaunchArgument("keyboard", default_value="false"),
        OpaqueFunction(function=setup),
    ])
