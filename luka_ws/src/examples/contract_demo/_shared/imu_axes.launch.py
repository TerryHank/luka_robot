"""Live IMU three-axis readout, with optional existing EKF."""
from pathlib import Path
import sys
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, OpaqueFunction, RegisterEventHandler
from launch.event_handlers import OnShutdown
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from interactive_support import SRC, active, nodes, enabled, claim, reserve_device


def setup(context):
    hardware = enabled(LaunchConfiguration("start_hardware").perform(context))
    ekf = enabled(LaunchConfiguration("with_ekf").perform(context))
    clear = claim("imu_axes", HERE / "imu_axes.launch.py")
    graph = nodes()
    actions = [RegisterEventHandler(OnShutdown(on_shutdown=clear))]
    if hardware and not active("luka-ws-hardware@sensors.service"):
        if not ({"/nx_imu", "/wit_imu_node"} & graph):
            reserve_device("imu_port")
            p = __import__("subprocess").run(["fuser", "/dev/nx_imu"], capture_output=True)
            if p.returncode == 0:
                raise RuntimeError("IMU serial port has an unknown owner.")
            actions.append(Node(
                package="ddsm_car_control", executable="wit_imu_node", name="nx_imu",
                parameters=[{"port": "/dev/nx_imu", "baud": 921600, "protocol": "normal",
                             "configure_output": False, "imu_topic": "/imu/data"}],
                output="screen"))
    if ekf and "/contract_demo/ekf_filter_node" not in graph:
        actions.append(ExecuteProcess(
            cmd=["ros2", "launch", str(HERE / "analysis.launch.py"), "mode:=ekf"], output="screen"))
    actions.append(ExecuteProcess(
        cmd=["python3", str(HERE / "telemetry_readout.py"), "--mode", "imu"],
        output="screen", additional_env={"PYTHONUNBUFFERED": "1"}))
    return actions


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument("start_hardware", default_value="true"),
        DeclareLaunchArgument("with_ekf", default_value="false"),
        OpaqueFunction(function=setup),
    ])
