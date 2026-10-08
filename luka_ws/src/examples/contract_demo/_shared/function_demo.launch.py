"""Real component launches and live readouts for contract clauses."""
import os
from pathlib import Path
import subprocess
import shlex
import socket
import sys
from launch import LaunchDescription
from launch.actions import (DeclareLaunchArgument, ExecuteProcess, IncludeLaunchDescription,
                            OpaqueFunction, RegisterEventHandler, EmitEvent)
from launch.event_handlers import OnShutdown, OnProcessExit
from launch.events import Shutdown
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from interactive_support import SRC, WS, active, nodes, enabled, claim, reserve_device

PROFILES = ("lidar", "camera", "interfaces", "layers", "slam", "map", "localization",
            "navigation", "avoidance", "business", "smoothing", "home", "voice",
            "face", "state_machine", "diagnostics")
NAV = {"layers", "navigation", "avoidance", "business", "smoothing", "home", "state_machine", "voice"}
BUSINESS = {"business", "home", "state_machine", "voice"}


def include(path, **arguments):
    return IncludeLaunchDescription(PythonLaunchDescriptionSource(str(path)),
                                   launch_arguments=arguments.items())


def process(cmd, cwd=None, env=None):
    action = ExecuteProcess(cmd=[str(s) for s in cmd], output="screen", cwd=cwd,
                            additional_env={"PYTHONUNBUFFERED": "1", **(env or {})})
    # A failed prerequisite must not leave the other demo processes running.
    return [action, RegisterEventHandler(OnProcessExit(
        target_action=action, on_exit=[EmitEvent(event=Shutdown(reason="demo component exited"))]))]


def service_environment(unit):
    p = subprocess.run(["systemctl", "show", unit, "-p", "Environment", "--value"],
                       capture_output=True, text=True, timeout=5, check=True)
    return dict(value.split("=", 1) for value in shlex.split(p.stdout) if "=" in value)


def tcp_free(port):
    with socket.socket() as sock:
        sock.settimeout(.3)
        if sock.connect_ex(("127.0.0.1", port)) == 0:
            raise RuntimeError("Unmanaged TCP listener on port %d; refusing duplicate service" % port)


def port_free(port):
    if subprocess.run(["fuser", port], capture_output=True).returncode == 0:
        raise RuntimeError(port + " already occupied; refusing a second hardware owner")


def setup(context):
    profile = LaunchConfiguration("profile").perform(context)
    if profile not in PROFILES:
        raise ValueError("Unknown device demonstration")
    clear = claim(profile, HERE / "function_demo.launch.py")
    actions = [RegisterEventHandler(OnShutdown(on_shutdown=clear))]
    map_yaml=Path(LaunchConfiguration("map_yaml").perform(context)).resolve()
    map_root=(WS.parent/"luka_data/maps").resolve()
    if not map_yaml.is_relative_to(map_root):
        raise RuntimeError("Demo map must be inside luka_data/maps")
    if enabled(LaunchConfiguration("start_hardware").perform(context)):

        graph = nodes()
        custom_map=map_yaml != (map_root/"ddsm_map_floor_4.yaml")
        if custom_map and (profile!="map" or not map_yaml.is_file()):
            raise RuntimeError("Custom map requires item10 and an existing YAML")
        if custom_map and {"/map_server","/amcl","/controller_server","/slam_toolbox"} & graph:
            raise RuntimeError("Stop existing map/navigation owners before isolated custom-map reload")

        # Map and odom TF must each have a single owner.
        if profile == "slam" and ({"/amcl", "/map_server", "/controller_server"} & graph):
            raise RuntimeError("Stop localization/navigation before SLAM; map/TF ownership conflicts")
        spatial = profile in NAV | {"slam", "map", "localization", "lidar", "interfaces"}
        if spatial:
            sensor_owners = {"/nx_imu", "/nx_upper_lidar", "/nx_lower_lidar"}
            existing = sensor_owners & graph
            if existing and existing != sensor_owners:
                raise RuntimeError("Partial sensor stack already running; stop it or reuse complete sensors")
            if not existing and not active("luka-ws-hardware@sensors.service"):
                reserve_device("imu_port")
                port_free("/dev/nx_imu")
                actions.append(include(SRC / "system/bringup/nx_sensors.launch.py"))
            base_owners = {"/nx_readonly_wheel_odom", "/zdt_mecanum_rs485_bridge"} & graph
            if len(base_owners) > 1:
                raise RuntimeError("Multiple base owners detected; resolve before demonstration")
            if profile in NAV and "/nx_readonly_wheel_odom" in base_owners:
                raise RuntimeError("Navigation needs protected base driver; stop read-only odometry first")
            if not base_owners:
                reserve_device("base_port")
                port_free("/dev/nx_base")
                if profile in NAV:
                    actions += process(["python3", SRC / "visualization/console/nx_manual_base.py",
                                        "--ros-args", "--params-file", SRC / "common/config/nx_manual_base.yaml",
                                        "-r", "odom:=/wheel/odom"])
                else:
                    actions += process(["python3", SRC / "visualization/console/nx_readonly_odom.py"])
        if profile == "lidar" and "/contract_demo_deskew" not in graph:
            actions.append(include(HERE / "analysis.launch.py", mode="deskew"))
        if profile == "slam":
            if "/slam_toolbox" not in graph:
                actions.append(include(HERE / "slam.launch.py"))
        elif profile in NAV | {"map", "localization"}:
            if "/slam_toolbox" in graph:
                raise RuntimeError("Stop SLAM before static-map localization")
            map_owners = {"/map_server", "/amcl"} & graph
            if map_owners and len(map_owners) != 2:
                raise RuntimeError("Partial localization already running; refusing duplicate map/TF owner")
            if not map_owners:
                actions.append(include(HERE / "localization.launch.py",map_yaml=str(map_yaml)))
        if profile in NAV:
            nav_owners = {"/controller_server", "/planner_server", "/collision_monitor",
                          "/velocity_smoother", "/bt_navigator", "/behavior_server",
                          "/smoother_server", "/lateral_escape_guard"}
            existing = nav_owners & graph
            if existing and existing != nav_owners:
                raise RuntimeError("Partial Nav2 stack running; refusing duplicate navigation owners")
            if not existing:
                actions.append(include(SRC / "system/bringup/nx_navigation.launch.py"))
        if profile in BUSINESS:
            owners = {"/ddsm_home_manager", "/ddsm_patrol_manager", "/ddsm_mission_control"}
            existing = owners & graph
            if existing and existing != owners:
                raise RuntimeError("Partial business stack running; refusing duplicate command owners")
            if not existing:
                actions.append(include(HERE / "business.launch.py"))
        if profile in {"camera", "face", "layers"}:
            if not active("luka-ws-orbbec-camera.service"):
                reserve_device("camera")
                if any("camera" in n for n in graph):
                    raise RuntimeError("Unmanaged camera running; use its complete service before demo")
                actions += process(["bash", SRC / "system/scripts/start_orbbec_camera.sh"])
        if profile == "face" and "/contract_demo_face_monitor" not in graph:
            actions += process(["python3",
                                HERE / "face_monitor.py"])
        if profile == "voice":
            cfg = SRC / "common/config/audio.env"
            env = {}
            for line in cfg.read_text().splitlines():
                if line.strip().startswith(("NX_MIC=", "NX_SPEAKER=")):
                    key, value = line.strip().split("=", 1)
                    env[key] = value.strip("'\"")
            if not all(env.get(k) for k in ("NX_MIC", "NX_SPEAKER")):
                raise RuntimeError("Configure NX_MIC/NX_SPEAKER in src/common/config/audio.env")
            if not active("luka-ws-chat.service"):
                tcp_free(8092)
                actions += process(["bash", SRC / "system/luka_xiaozhi/scripts/start_oellm.sh"],
                                   env=service_environment("luka-ws-chat.service"))
            if not active("luka-ws-agent.service"):
                if "/nav_llm_agent" in graph:
                    raise RuntimeError("Unmanaged command agent running")
                actions += process(["bash", SRC / "system/bringup/start_nx_agent.sh"], env=service_environment("luka-ws-agent.service"))
            if not active("luka-ws-hardware@voice.service"):
                if any("voice_gateway" in n for n in graph):
                    raise RuntimeError("Unmanaged voice gateway running")
                actions += process(["bash", SRC / "system/bringup/start_nx_voice.sh"], env={**service_environment("luka-ws-hardware@voice.service"), **env})
        if profile in NAV | {"slam", "map"} and "/contract_demo_native" not in graph:
            actions += process(["python3", HERE / "native_commands.py"])
    actions += process(["python3", HERE / "function_readout.py", "--profile", profile])
    print("Live demonstration:", profile, "| Foxglove ws://192.168.3.150:8765", flush=True)
    print("No goal is sent at startup. WAITING/STALE is not functional acceptance.", flush=True)
    return actions


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument("profile", default_value="diagnostics"),
        DeclareLaunchArgument("map_yaml",default_value=str(WS.parent/"luka_data/maps/ddsm_map_floor_4.yaml")),

        DeclareLaunchArgument("start_hardware", default_value="true",
                              description="false: isolated/replay monitoring, not hardware acceptance"),
        OpaqueFunction(function=setup),
    ])