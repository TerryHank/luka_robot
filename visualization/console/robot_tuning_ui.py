#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import os
import re
import shlex
import shutil
import socket
import subprocess
import time
import fcntl
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components
from ruamel.yaml import YAML
from mapping_bundle import save_bundle


WS = Path(os.environ.get("DDSM_WS", "/home/sunrise/luka_ws"))
ENV_FILE = WS / "common/config/runtime_tuning.env"
NAV_FILE = (
    WS
    / "src/ddsm_car_control/config/nav2_mecanum_mppi_params.yaml"
)
OMNI_NAV_FILE = (
    WS
    / "src/ddsm_car_control/config/nav2_mecanum_mppi_omni_params.yaml"
)
GAMEPAD_FILE = WS / "src/ddsm_car_control/config/flydigi_vader4pro.yaml"
RESTART_SCRIPT = WS / "system/bringup/restart_nav_reset.sh"
LIGHT_DASHBOARD_SCRIPT = WS / "system/runtime/tools/start_lightweight_dashboard.sh"
EXPLORE_SCRIPT = WS / "system/bringup/restart_explore_mapping.sh"
BUILDING_FILE = WS / "common/config/multifloor_building.yaml"
ACTIVE_FLOOR_CONTEXT_FILE = WS / "common/config/active_floor_context.json"
NAVIGATION_MOTION_MODE_FILE = WS / "common/config/navigation_motion_mode.txt"
MAPS_DIR = WS / "map/maps"
UI_LOG = WS / "log/robot_tuning_ui_restart.log"
MAP_SAVE_LOG = WS / "log/robot_tuning_ui_map_save.log"
VISION_BRIDGE_SCRIPT = WS / "system/runtime/tools/vision_frontend_bridge.py"
VISION_FRAME_FILE = Path("/tmp/ddsm_semantic_annotated.jpg")
VISION_STATUS_FILE = Path("/tmp/ddsm_semantic_status.json")
VISION_PID_FILE = Path("/tmp/ddsm_vision_frontend_bridge.pid")
VISION_LOCK_FILE = Path("/tmp/ddsm_vision_frontend_bridge.lock")
VISION_LOG = WS / "log/vision_frontend_bridge.log"
VISION_HTTP_PORT = int(os.environ.get("VISION_HTTP_PORT", "8502"))

yaml = YAML()
yaml.preserve_quotes = True
yaml.width = 1000


def vision_bridge_port_ready(timeout: float = 0.15) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", VISION_HTTP_PORT), timeout=timeout):
            return True
    except OSError:
        return False


def vision_bridge_running() -> bool:
    if vision_bridge_port_ready():
        return True
    if not VISION_PID_FILE.exists():
        return False
    try:
        pid = int(VISION_PID_FILE.read_text(encoding="utf-8").strip())
        os.kill(pid, 0)
        command = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ")
        return b"vision_frontend_bridge.py" in command
    except (OSError, ValueError):
        VISION_PID_FILE.unlink(missing_ok=True)
        return False


def ensure_vision_bridge() -> tuple[bool, str]:
    if not VISION_BRIDGE_SCRIPT.exists():
        return False, f"缺少视觉画面桥接脚本：{VISION_BRIDGE_SCRIPT}"

    VISION_LOCK_FILE.touch(exist_ok=True)
    with VISION_LOCK_FILE.open("r+") as lock_stream:
        fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX)
        if vision_bridge_running():
            return True, "视觉画面桥接已运行"

        # A single service owns port 8502. Do not race it with a second nohup
        # process when a browser refresh arrives during startup/recovery.
        service_file = Path.home() / ".config/systemd/user/luca-vision-bridge.service"
        if service_file.is_file():
            try:
                result = subprocess.run(
                    ["systemctl", "--user", "start", "luca-vision-bridge.service"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                    text=True, timeout=8,
                )
            except (OSError, subprocess.TimeoutExpired):
                return False, "视觉桥接服务启动超时，请查看用户服务日志"
            if result.returncode:
                return False, "视觉桥接服务启动失败，请查看用户服务日志"
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline:
                if vision_bridge_port_ready():
                    return True, "视觉画面桥接服务已启动"
                time.sleep(0.1)
            return False, "视觉桥接服务启动中，请稍后刷新"

        VISION_LOG.parent.mkdir(parents=True, exist_ok=True)
        command = (
            "set +u; "
            "source /opt/ros/humble/setup.bash; "
            f"source {shlex.quote(str(WS / 'install/setup.bash'))}; "
            "export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp; "
            f"export CYCLONEDDS_URI=file://{shlex.quote(str(WS / 'common/config/cyclonedds_nav2.xml'))}; "
            "set -u; "
            f"exec /usr/bin/python3 {shlex.quote(str(VISION_BRIDGE_SCRIPT))}"
        )
        with VISION_LOG.open("ab") as log_stream:
            process = subprocess.Popen(
                ["bash", "-lc", command],
                stdin=subprocess.DEVNULL,
                stdout=log_stream,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        VISION_PID_FILE.write_text(str(process.pid), encoding="utf-8")
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            if vision_bridge_port_ready():
                return True, "视觉画面桥接已启动"
            if process.poll() is not None:
                break
            time.sleep(0.1)

        VISION_PID_FILE.unlink(missing_ok=True)
        return False, f"视觉画面桥接启动失败，请查看 {VISION_LOG}"


@st.fragment(run_every=1.0)
def render_vision_monitor() -> None:
    bridge_ok, bridge_message = ensure_vision_bridge()
    status: dict = {}
    if VISION_STATUS_FILE.exists():
        try:
            status = json.loads(VISION_STATUS_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            status = {}

    image_age = None
    if VISION_FRAME_FILE.exists():
        image_age = max(0.0, time.time() - VISION_FRAME_FILE.stat().st_mtime)

    status_col, delay_col = st.columns([3, 1])
    with status_col:
        st.code(status.get("semantic_status", bridge_message), language=None)
    with delay_col:
        st.metric("画面延迟", f"{image_age:.1f} s" if image_age is not None else "--")

    if not bridge_ok:
        st.error(bridge_message)
    elif not VISION_FRAME_FILE.exists():
        st.warning("尚未收到识别画面，请确认已启动视觉识别节点。")
    else:
        if image_age is not None and image_age > 5.0:
            st.warning("识别画面已超过 5 秒未更新。")
        components.html(
            f"""
            <style>
              html, body {{ margin: 0; background: transparent; }}
              .vision-grid {{
                display: grid;
                grid-template-columns: repeat(2, minmax(0, 1fr));
                gap: 12px;
              }}
              .vision-label {{ color: #c6ccd5; margin-bottom: 6px; font: 14px sans-serif; }}
              .vision-frame {{
                display: block;
                width: 100%;
                height: auto;
                min-height: 180px;
                object-fit: contain;
                border-radius: 6px;
              }}
              @media (max-width: 760px) {{ .vision-grid {{ grid-template-columns: 1fr; }} }}
            </style>
            <div class="vision-grid">
              <div><div class="vision-label">实时相机</div><img id="live-frame" class="vision-frame" alt="实时相机画面"></div>
              <div><div class="vision-label">最近一次识别结果</div><img id="detection-frame" class="vision-frame" alt="语义识别结果"></div>
            </div>
            <script>
              const host = window.parent.location.hostname || "192.168.3.150";
              function refreshFrame(elementId, fileName) {{
                const image = document.getElementById(elementId);
                const next = new Image();
                next.onload = () => {{ image.src = next.src; }};
                next.src = `http://${{host}}:{VISION_HTTP_PORT}/${{fileName}}?t=${{Date.now()}}`;
              }}
              refreshFrame("live-frame", "frame.jpg");
              refreshFrame("detection-frame", "detection.jpg");
              window.setInterval(() => refreshFrame("live-frame", "frame.jpg"), 500);
              window.setInterval(() => refreshFrame("detection-frame", "detection.jpg"), 1000);
            </script>
            """,
            height=620,
            scrolling=False,
        )

    st.caption(
        "实时画面：/camera/color/image_raw  |  "
        "识别结果：/semantic_mapping/annotated_image  |  自动刷新"
    )


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def env_float(values: dict[str, str], key: str, default: float) -> float:
    try:
        return float(values.get(key, default))
    except (TypeError, ValueError):
        return default


def backup(path: Path) -> None:
    if not path.exists():
        return
    stamp = time.strftime("%Y%m%d_%H%M%S")
    shutil.copy2(path, path.with_name(f"{path.name}.bak_ui_{stamp}"))


def write_yaml_atomic(path: Path, data: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        yaml.dump(data, stream)
    temporary.replace(path)


def write_env_atomic(path: Path, values: dict[str, str]) -> None:
    temporary = path.with_suffix(".env.tmp")
    lines = [
        "# Robot runtime tuning. Managed by robot_tuning_ui.py.",
        *[f"{key}={value}" for key, value in values.items()],
        "",
    ]
    temporary.write_text("\n".join(lines), encoding="utf-8")
    temporary.replace(path)


def load_yaml_file(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as stream:
        return yaml.load(stream) or {}


def floor_id_from_map(path: Path) -> str:
    match = re.search(r"floor[_-]?(\d+)", path.stem, re.IGNORECASE)
    return f"floor_{match.group(1)}" if match else "floor_1"


def available_maps() -> list[Path]:
    return sorted(MAPS_DIR.glob("*.yaml"), key=lambda path: path.name)


def available_floor_ids(building: dict) -> list[str]:
    floor_ids = list((building.get("floors") or {}).keys())
    semantic_dir = WS / "common/config/semantic"
    if semantic_dir.exists():
        floor_ids.extend(
            path.name for path in semantic_dir.iterdir() if path.is_dir()
        )
    return sorted(set(floor_ids)) or ["floor_1"]


def configured_floor_id(building: dict) -> str:
    fallback = str(building.get("current_floor_id", "floor_1"))
    if not ACTIVE_FLOOR_CONTEXT_FILE.exists():
        return fallback
    try:
        context = json.loads(ACTIVE_FLOOR_CONTEXT_FILE.read_text(encoding="utf-8"))
        floor_id = str(context.get("floor_id") or "").strip()
    except (OSError, ValueError, json.JSONDecodeError):
        return fallback
    return floor_id if floor_id in (building.get("floors") or {}) else fallback


def floor_default_map(building: dict, floor_id: str, maps: list[Path]) -> Path | None:
    configured = ((building.get("floors") or {}).get(floor_id) or {}).get("map")
    if configured:
        candidate = Path(str(configured))
        if candidate.exists():
            return candidate
    return next(
        (path for path in maps if floor_id_from_map(path) == floor_id),
        maps[0] if maps else None,
    )


def floor_pois(floor_id: str) -> list[dict]:
    poi_file = WS / f"common/config/semantic/{floor_id}/pois.yaml"
    data = load_yaml_file(poi_file)
    return [
        dict(item)
        for item in (data.get("pois") or [])
        if item.get("enabled", True)
    ]


def ros_command(arguments: list[str], timeout: float = 12.0) -> tuple[bool, str]:
    command = " ".join(shlex.quote(str(argument)) for argument in arguments)
    shell = (
        "unset ROS_LOCALHOST_ONLY; "
        "export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET; "
        "export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp; "
        f"export CYCLONEDDS_URI=file://{shlex.quote(str(WS / 'common/config/cyclonedds_nav2.xml'))}; "
        "export FASTDDS_BUILTIN_TRANSPORTS=UDPv4; "
        "set +u; "
        "source /opt/ros/humble/setup.bash; "
        f"source {shlex.quote(str(WS / 'install/setup.bash'))}; "
        "set -u; "
        f"ros2 {command}"
    )
    try:
        result = subprocess.run(
            ["/bin/bash", "-lc", shell],
            cwd=str(WS),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, f"命令超过 {timeout:.0f} 秒未完成，请检查对应节点是否已启动。"
    output = "\n".join(
        part.strip() for part in (result.stdout, result.stderr) if part.strip()
    )
    return result.returncode == 0, output or f"命令退出码: {result.returncode}"


def publish_string(topic: str, value: str) -> tuple[bool, str]:
    message = json.dumps({"data": value}, ensure_ascii=False)
    return ros_command(
        ["topic", "pub", "--once", "-w", "1", topic, "std_msgs/msg/String", message],
        timeout=10.0,
    )


def navigation_motion_profile() -> str:
    try:
        mode = NAVIGATION_MOTION_MODE_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        mode = ""
    return "front_forward" if mode == "forward_facing" else "omni"


def set_navigation_motion_profile(
    profile: str, *, publish: bool = True
) -> tuple[bool, str]:
    if profile not in ("front_forward", "omni"):
        return False, f"不支持的导航运动模式：{profile}"
    mode = "forward_facing" if profile == "front_forward" else "omni"
    NAVIGATION_MOTION_MODE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = NAVIGATION_MOTION_MODE_FILE.with_suffix(".tmp")
    temporary.write_text(mode + "\n", encoding="utf-8")
    os.replace(temporary, NAVIGATION_MOTION_MODE_FILE)
    if not publish:
        return True, f"已保存模式：{mode}"
    ok, detail = publish_string("/navigation/motion_mode", mode)
    if ok:
        return True, "车头朝向模式已生效" if mode == "forward_facing" else "全向模式已生效"
    return True, f"模式已保存，将在导航启动时生效。当前导航节点未响应：{detail}"


def publish_empty(topic: str) -> tuple[bool, str]:
    return ros_command(
        ["topic", "pub", "--once", "-w", "1", topic, "std_msgs/msg/Empty", "{}"],
        timeout=10.0,
    )


def publish_elevator_status(floor_id: str) -> tuple[bool, str]:
    status = json.dumps(
        {
            "available": True,
            "door": "open",
            "floor_id": floor_id,
            "car_present": True,
            "motion": "stopped",
        },
        ensure_ascii=False,
    )
    return publish_string("/hotel/elevator/manual/status", status)


def call_empty_service(service: str) -> tuple[bool, str]:
    return ros_command(
        ["service", "call", service, "std_srvs/srv/Empty", "{}"],
        timeout=6.0,
    )


def start_background(script: Path, environment_values: dict[str, str]) -> None:
    UI_LOG.parent.mkdir(parents=True, exist_ok=True)
    log_stream = UI_LOG.open("a", encoding="utf-8")
    environment = os.environ.copy()
    environment.update(environment_values)
    subprocess.Popen(
        [str(script)],
        cwd=str(WS),
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=log_stream,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )


def ensure_lightweight_dashboard() -> None:
    if not LIGHT_DASHBOARD_SCRIPT.exists():
        return
    UI_LOG.parent.mkdir(parents=True, exist_ok=True)
    log_stream = UI_LOG.open("a", encoding="utf-8")
    subprocess.Popen(
        [str(LIGHT_DASHBOARD_SCRIPT), "start"],
        cwd=str(WS),
        env=os.environ.copy(),
        stdin=subprocess.DEVNULL,
        stdout=log_stream,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )


def restart_navigation(
    map_path: Path | None = None,
    floor_id: str | None = None,
    multifloor: bool = False,
    motion_profile: str = "front_forward",
) -> tuple[bool, str]:
    visual_floor = floor_id or "floor_1"
    nav_params_file = OMNI_NAV_FILE if motion_profile == "omni" else NAV_FILE
    motion_mode = "forward_facing" if motion_profile == "front_forward" else "omni"
    set_navigation_motion_profile(motion_profile, publish=False)
    environment = {
        "RESTART_FOXGLOVE": "0",
        "MODE": "auto_nav",
        "NAV_PARAMS_FILE": str(nav_params_file),
        "NAVIGATION_MOTION_MODE": motion_mode,
        "TUNING_ENV_FILE": str(ENV_FILE),
        "ENABLE_MULTIFLOOR_MANAGER": "true" if multifloor else "false",
        "ENABLE_DEPTH_CAMERA": "true",
        "ENABLE_SEMANTIC_MAPPING": "true",
        "SEMANTIC_FLOOR_ID": visual_floor,
        "SEMANTIC_OUTPUT_FILE": str(
            WS / "common/config/semantic_auto" / visual_floor / "detections.yaml"
        ),
    }
    if map_path is not None:
        environment["MAP"] = str(map_path)
    if floor_id:
        environment["FLOOR_ID"] = floor_id
        environment["MULTIFLOOR_CURRENT_FLOOR_ID"] = floor_id

    preflight_environment = os.environ.copy()
    preflight_environment.update(environment)
    preflight_environment["PREFLIGHT_ONLY"] = "1"
    preflight_environment["LIDAR_PREFLIGHT_TIMEOUT"] = "10"
    try:
        preflight = subprocess.run(
            [str(RESTART_SCRIPT)],
            cwd=str(WS),
            env=preflight_environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=45.0,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, "雷达自检超时，已阻止重启；现有导航进程未被停止。"
    if preflight.returncode != 0:
        detail = "\n".join(preflight.stdout.strip().splitlines()[-4:])
        return False, (
            "雷达没有实时数据，已阻止重启；现有导航进程未被停止。"
            "请将雷达和 S2E 转换盒断电约 5 秒后重新上电，再点一次。"
            f"\n\n{detail}"
        )

    start_background(RESTART_SCRIPT, environment)
    ensure_lightweight_dashboard()
    return True, "雷达实时数据自检通过，已提交后台重启。"


def start_explore_mapping(floor_id: str) -> None:
    start_background(
        EXPLORE_SCRIPT,
        {
            "RESTART_FOXGLOVE": "0",
            "MODE": "explore",
            "TUNING_ENV_FILE": str(ENV_FILE),
            "FLOOR_ID": floor_id,
            "ENABLE_DEPTH_CAMERA": "true",
            "ENABLE_SEMANTIC_MAPPING": "true",
            "SEMANTIC_FLOOR_ID": floor_id,
            "SEMANTIC_OUTPUT_FILE": str(
                WS / "common/config/semantic_auto" / floor_id / "detections.yaml"
            ),
        },
    )


def stop_robot_stack() -> tuple[bool, str]:
    zero_twist = json.dumps(
        {
            "linear": {"x": 0.0, "y": 0.0, "z": 0.0},
            "angular": {"x": 0.0, "y": 0.0, "z": 0.0},
        }
    )
    for topic in ("/cmd_vel", "/cmd_vel_nav", "/cmd_vel_nav_raw", "/cmd_vel_teleop"):
        ros_command(
            [
                "topic",
                "pub",
                "--once",
                "-w",
                "0",
                topic,
                "geometry_msgs/msg/Twist",
                zero_twist,
            ],
            timeout=2.0,
        )

    environment = os.environ.copy()
    environment.update(
        {
            "RESTART_FOXGLOVE": "0",
            "STOP_ONLY": "1",
            "TUNING_ENV_FILE": str(ENV_FILE),
        }
    )
    try:
        result = subprocess.run(
            [str(RESTART_SCRIPT)],
            cwd=str(WS),
            env=environment,
            capture_output=True,
            text=True,
            timeout=20.0,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, "关闭超过 20 秒，请检查仍在运行的机器人节点。"
    output = "\n".join(
        part.strip() for part in (result.stdout, result.stderr) if part.strip()
    )
    return result.returncode == 0, output or f"命令退出码: {result.returncode}"


def normalized_map_name(raw_name: str) -> str:
    name = raw_name.strip()
    for suffix in (".yaml", ".pgm", ".png"):
        if name.lower().endswith(suffix):
            name = name[: -len(suffix)]
    if not name:
        raise ValueError("请输入地图名称。")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
        raise ValueError("地图名称只能包含字母、数字、下划线和短横线。")
    if not name.startswith("ddsm_map_"):
        name = f"ddsm_map_{name}"
    return name


def save_live_map(raw_name: str, overwrite: bool) -> tuple[bool, str]:
    try:
        map_name = normalized_map_name(raw_name)
    except ValueError as exc:
        return False, str(exc)
    base_path = MAPS_DIR / map_name
    existing = [
        path
        for path in (
            base_path.with_suffix(".yaml"),
            base_path.with_suffix(".pgm"),
            base_path.with_suffix(".png"),
        )
        if path.exists()
    ]
    if existing and not overwrite:
        return False, "同名地图已存在。勾选“允许覆盖”后才能替换。"
    if overwrite:
        for path in existing:
            backup(path)
    success, output = ros_command(
        [
            "run",
            "nav2_map_server",
            "map_saver_cli",
            "-f",
            str(base_path),
            "--ros-args",
            "-p",
            "save_map_timeout:=10.0",
        ],
        timeout=25.0,
    )
    MAP_SAVE_LOG.parent.mkdir(parents=True, exist_ok=True)
    MAP_SAVE_LOG.write_text(output + "\n", encoding="utf-8")
    yaml_path = base_path.with_suffix(".yaml")
    if success and yaml_path.exists():
        return True, f"地图已保存：{yaml_path}"
    return False, output


st.set_page_config(
    page_title="DDSM Robot Control",
    page_icon="",
    layout="wide",
)
st.title("DDSM 小车控制台")
st.caption("导航、跨楼层和建图均从这里启动。所有重启操作都会保留 Foxglove Bridge。")

if st.button("一键关闭小车系统", use_container_width=True):
    with st.spinner("正在发送零速度并关闭机器人节点..."):
        stopped, stop_result = stop_robot_stack()
    if stopped:
        st.success("小车系统已关闭，Foxglove Bridge 和本控制前端保持运行。")
    else:
        st.error(stop_result)

env_values = read_env(ENV_FILE)
nav = load_yaml_file(NAV_FILE)
gamepad = load_yaml_file(GAMEPAD_FILE)
building = load_yaml_file(BUILDING_FILE)
map_files = available_maps()
floor_ids = available_floor_ids(building)

controller = nav["controller_server"]["ros__parameters"]
mppi = controller["FollowPath"]
smoother = nav["velocity_smoother"]["ros__parameters"]
local_costmap = nav["local_costmap"]["local_costmap"]["ros__parameters"]
global_costmap = nav["global_costmap"]["global_costmap"]["ros__parameters"]
joy = gamepad["joy_node"]["ros__parameters"]
teleop = gamepad["gamepad_teleop"]["ros__parameters"]

tab_control, tab_vision, tab_speed, tab_frequency, tab_manual = st.tabs(
    ["任务控制", "视觉监控", "导航与底盘", "传感器与刷新率", "手柄"]
)

with tab_control:
    nav_tab, mapping_tab = st.tabs(["导航任务", "地图管理"])

    with nav_tab:
        floor_col, map_col, mode_col = st.columns([1, 2, 1])
        with floor_col:
            configured_floor = configured_floor_id(building)
            context_revision = (
                f"{configured_floor}:"
                f"{ACTIVE_FLOOR_CONTEXT_FILE.stat().st_mtime_ns}"
                if ACTIVE_FLOOR_CONTEXT_FILE.exists()
                else f"{configured_floor}:building"
            )
            if st.session_state.get("active_floor_context_revision") != context_revision:
                st.session_state["nav_floor_select"] = configured_floor
                st.session_state["active_floor_context_revision"] = context_revision
            selected_floor = st.selectbox(
                "当前楼层",
                floor_ids,
                index=floor_ids.index(configured_floor)
                if configured_floor in floor_ids
                else 0,
                key="nav_floor_select",
            )
        default_map = floor_default_map(building, selected_floor, map_files)
        with map_col:
            selected_map = st.selectbox(
                "导航地图",
                map_files,
                index=map_files.index(default_map)
                if default_map in map_files
                else 0,
                format_func=lambda path: path.stem,
                key=f"nav_map_{selected_floor}",
            ) if map_files else None
        with mode_col:
            multifloor_enabled = st.checkbox("启用多地图导航", value=False)

        stored_motion_profile = navigation_motion_profile()
        motion_profile = st.radio(
            "导航运动模式",
            options=("front_forward", "omni"),
            format_func=lambda value: {
                "front_forward": "车头朝向模式（禁止斜行）",
                "omni": "全向模式（允许斜行）",
            }[value],
            index=0 if stored_motion_profile == "front_forward" else 1,
            horizontal=True,
            help="车头朝向模式会先转动车头对准路径，再向前行驶；全向模式允许直接横移。",
        )

        if st.button("立即应用运动模式", use_container_width=True):
            mode_ok, mode_message = set_navigation_motion_profile(motion_profile)
            if mode_ok:
                st.success(mode_message)
            else:
                st.error(mode_message)

        if st.button(
            "一键启动导航模式",
            type="primary",
            use_container_width=True,
            disabled=selected_map is None,
        ):
            restart_ok, restart_message = restart_navigation(
                selected_map,
                selected_floor,
                multifloor_enabled,
                motion_profile,
            )
            mode_text = "多地图" if multifloor_enabled else "单地图"
            motion_text = (
                "车头朝前" if motion_profile == "front_forward" else "全向麦轮"
            )
            if restart_ok:
                st.success(
                    f"{restart_message}{mode_text}导航（{motion_text}）："
                    f"{selected_floor} / {selected_map.stem}。"
                    "Foxglove Bridge 保持运行，定位完成后再发送航点。"
                )
            else:
                st.error(restart_message)

        st.divider()
        st.subheader("发送目的地")
        if multifloor_enabled:
            destination_data = building.get("destinations") or {}
            destinations = list(destination_data.keys())
            destination_labels = {
                key: (
                    f"{value.get('display_name', key)} · "
                    f"{value.get('floor_id', '未知楼层')} ({key})"
                )
                for key, value in destination_data.items()
            }
            destination_topic = "/hotel/floor_goal"
        else:
            poi_data = floor_pois(selected_floor)
            destinations = [str(item.get("id")) for item in poi_data if item.get("id")]
            destination_labels = {
                str(item.get("id")): (
                    f"{item.get('display_name', item.get('id'))} ({item.get('id')})"
                )
                for item in poi_data
                if item.get("id")
            }
            destination_topic = "/hotel/goal_destination"

        dest_col, custom_col = st.columns(2)
        with dest_col:
            selected_destination = st.selectbox(
                "已命名航点",
                destinations,
                format_func=lambda value: destination_labels.get(value, value),
                disabled=not destinations,
            ) if destinations else ""
        with custom_col:
            custom_destination = st.text_input(
                "航点 ID 或显示名称",
                placeholder="留空则使用左侧已命名航点",
            ).strip()
        destination_value = custom_destination or selected_destination

        send_col, cancel_col = st.columns(2)
        with send_col:
            if st.button(
                "发送导航任务",
                type="primary",
                use_container_width=True,
                disabled=not destination_value,
            ):
                ok, result = publish_string(destination_topic, destination_value)
                if ok:
                    st.success(f"已发送：{destination_value}")
                    if multifloor_enabled:
                        time.sleep(0.5)
                        st.rerun()
                else:
                    st.error(result)
        with cancel_col:
            if st.button(
                "取消跨楼层任务",
                use_container_width=True,
                disabled=not multifloor_enabled,
            ):
                ok, result = publish_empty("/hotel/floor_mission/cancel")
                if ok:
                    st.success("跨楼层任务已取消。")
                else:
                    st.error(result)

        st.divider()
        st.subheader("任务运行控制")
        mission_state = load_yaml_file(WS / "common/config/mission_state.yaml")
        floor_state = load_yaml_file(WS / "common/config/floor_mission_state.yaml")
        current_state = str(mission_state.get("state", "未知"))
        floor_task_state = str(floor_state.get("state", "idle"))
        floor_task_active = floor_task_state not in {
            "",
            "idle",
            "canceled",
            "failed",
            "succeeded",
        }
        if multifloor_enabled or floor_task_active:
            current_state = (
                f"{current_state} / 楼层任务 "
                f"{floor_task_state}"
            )
        st.caption(f"当前状态：{current_state}")

        if multifloor_enabled or floor_task_active:
            current_floor = str(floor_state.get("current_floor_id", ""))
            target_floor = str(floor_state.get("target_floor_id", ""))
            instruction = str(floor_state.get("instruction", ""))
            floor_error = str(floor_state.get("error", ""))
            st.caption(
                f"电梯流程：{current_floor or '未知'} -> {target_floor or '未知'}"
            )
            if instruction:
                st.info(instruction)
            if floor_error:
                st.error(floor_error)

            with st.expander("人工电梯联调", expanded=floor_task_active):
                st.caption("按当前任务状态从左到右确认；不满足条件的按钮会锁定。")
                lobby_col, source_open_col, entered_col = st.columns(3)
                with lobby_col:
                    if st.button(
                        "1. 到达电梯厅",
                        use_container_width=True,
                        disabled=floor_task_state != "going_to_elevator",
                    ):
                        ok, result = publish_empty("/hotel/elevator/lobby_ready")
                        if ok:
                            st.success("已确认到达电梯厅。")
                            time.sleep(0.5)
                            st.rerun()
                        else:
                            st.error(result)
                with source_open_col:
                    if st.button(
                        "2. 当前层门已开",
                        use_container_width=True,
                        disabled=(
                            floor_task_state != "waiting_elevator"
                            or not current_floor
                        ),
                    ):
                        ok, result = publish_elevator_status(current_floor)
                        if ok:
                            st.success(f"已确认 {current_floor} 电梯门打开。")
                            time.sleep(0.5)
                            st.rerun()
                        else:
                            st.error(result)
                with entered_col:
                    if st.button(
                        "3. 已安全进电梯",
                        use_container_width=True,
                        disabled=floor_task_state != "ready_to_enter",
                    ):
                        ok, result = publish_empty("/hotel/elevator/entered")
                        if ok:
                            st.success("已确认机器人进入电梯。")
                            time.sleep(0.5)
                            st.rerun()
                        else:
                            st.error(result)

                target_open_col, exited_col = st.columns(2)
                with target_open_col:
                    if st.button(
                        "4. 目标层门已开",
                        use_container_width=True,
                        disabled=(
                            floor_task_state != "riding_elevator"
                            or not target_floor
                        ),
                    ):
                        ok, result = publish_elevator_status(target_floor)
                        if ok:
                            st.success(f"已确认 {target_floor} 电梯门打开。")
                            time.sleep(0.5)
                            st.rerun()
                        else:
                            st.error(result)
                with exited_col:
                    if st.button(
                        "5. 已安全出电梯",
                        type="primary",
                        use_container_width=True,
                        disabled=floor_task_state != "ready_to_exit",
                    ):
                        ok, result = publish_empty("/hotel/elevator/exited")
                        if ok:
                            st.success("已确认出梯，系统将切换地图并继续导航。")
                            time.sleep(0.5)
                            st.rerun()
                        else:
                            st.error(result)

        pause_col, resume_col, stop_col = st.columns(3)
        with pause_col:
            if st.button("暂停任务", use_container_width=True):
                ok, result = call_empty_service("/hotel/mission/pause_now")
                if ok:
                    st.success("已暂停，当前位置和目标任务已保留。")
                else:
                    st.error(result)
        with resume_col:
            if st.button("恢复任务", type="primary", use_container_width=True):
                ok, result = call_empty_service("/hotel/mission/resume_now")
                if ok:
                    st.success("已恢复当前任务。")
                else:
                    st.error(result)
        with stop_col:
            if st.button("取消任务", use_container_width=True):
                service_ok, service_result = call_empty_service(
                    "/hotel/mission/cancel_now"
                )
                floor_ok = True
                floor_result = ""
                if multifloor_enabled or floor_task_active:
                    floor_ok, floor_result = publish_empty(
                        "/hotel/floor_mission/cancel"
                    )
                if service_ok and floor_ok:
                    st.success("当前任务已取消，残留目标已清理。")
                else:
                    st.error(
                        "\n".join(
                            result
                            for result in (service_result, floor_result)
                            if result
                        )
                    )

        with st.expander("多地图任务状态与配置"):
            state_file = WS / "common/config/floor_mission_state.yaml"
            if state_file.exists():
                st.code(state_file.read_text(encoding="utf-8"), language="yaml")
            st.caption(f"多楼层配置：{BUILDING_FILE}")

    with mapping_tab:
        st.subheader("手动带车建图")
        st.caption("不启动自主探索。用手柄慢速带车；先松开手柄停稳，再保存。旧地图不会被覆盖。")
        mapping_safe = st.checkbox("我在现场，已确认周围安全，手柄可随时停止小车", key="manual_mapping_safe")
        if st.button("启动手动建图", disabled=not mapping_safe, use_container_width=True):
            start_background(WS / "system/runtime/tools/start_manual_mapping.sh", {})
            st.info("已提交启动请求，并非已经就绪。请查看实时地图和启动日志后再操作手柄。")
        st.link_button("查看实时地图", "http://192.168.3.150:8503", use_container_width=True)
        if st.button("检查建图节点状态", use_container_width=True):
            ready, detail = ros_command(["lifecycle", "get", "/slam_toolbox"], timeout=8)
            if ready and re.search(r"\bactive\s*\[3\]", detail):
                st.success("SLAM 已激活。还需确认实时地图有数据，并随手动移动更新。")
            else:
                st.warning("建图尚未就绪，请等待启动完成或查看启动日志。")
        bundle_label = st.text_input("新地图标签", value="manual_map", key="mapping_bundle_label")
        mapping_stopped = st.checkbox("已松开手柄，小车保持静止", key="mapping_stopped")
        if st.button("另存完整地图与建图会话", disabled=not mapping_stopped, use_container_width=True):
            with st.spinner("正在保存地图与建图会话，请保持小车静止…"):
                ok, message = save_bundle(MAPS_DIR / "sessions", bundle_label, ros_command)
            if ok:
                st.success(message)
            else:
                st.error(message)
        st.divider()
        st.subheader("自动探索建图")
        st.caption(
            "启动 explore_lite、SLAM Toolbox、底盘、雷达、深度相机和视觉识别服务。"
        )
        configured_floor = configured_floor_id(building)
        mapping_floor = st.selectbox(
            "建图楼层",
            floor_ids,
            index=floor_ids.index(configured_floor)
            if configured_floor in floor_ids
            else 0,
            key="mapping_floor",
        )
        if st.button(
            "一键启动自动建图",
            type="primary",
            use_container_width=True,
        ):
            start_explore_mapping(mapping_floor)
            st.success(
                f"已开始后台启动 {mapping_floor} 自动建图和视觉识别。"
                "Foxglove 中查看 /map、/map_updates、/scan 和 "
                "/semantic_mapping/annotated_image。"
            )

        st.divider()
        st.subheader("命名并保存当前地图")
        save_col, overwrite_col = st.columns([3, 1])
        with save_col:
            new_map_name = st.text_input(
                "地图名称",
                placeholder="例如 floor_3，将保存为 ddsm_map_floor_3",
            )
        with overwrite_col:
            overwrite_map = st.checkbox("允许覆盖同名地图", value=False)
        if st.button(
            "一键保存地图",
            use_container_width=True,
            disabled=not new_map_name.strip(),
        ):
            ok, result = save_live_map(new_map_name, overwrite_map)
            if ok:
                st.success(result)
            else:
                st.error(result)

        if map_files:
            st.caption("现有地图：" + "、".join(path.stem for path in map_files))

with tab_vision:
    st.subheader("相机识别画面")
    st.caption("显示语义识别节点输出的目标框、类别和识别状态。")
    render_vision_monitor()

with tab_speed:
    col1, col2, col3 = st.columns(3)
    with col1:
        driver_linear = st.number_input(
            "底盘直线总限速 (m/s)",
            0.05,
            3.0,
            env_float(env_values, "MAX_LINEAR_SPEED", 1.8),
            0.05,
        )
        nav_forward = st.number_input(
            "导航前进限速 vx (m/s)", 0.05, 2.0, float(mppi["vx_max"]), 0.05
        )
        nav_reverse = st.number_input(
            "导航后退限速 (m/s)",
            0.0,
            1.0,
            abs(float(mppi["vx_min"])),
            0.02,
        )
    with col2:
        nav_lateral = st.number_input(
            "导航横移限速 vy (m/s)", 0.0, 1.5, float(mppi["vy_max"]), 0.02
        )
        nav_angular = st.number_input(
            "导航旋转限速 wz (rad/s)", 0.1, 8.0, float(mppi["wz_max"]), 0.1
        )
        driver_angular = st.number_input(
            "底盘旋转总限速 (rad/s)",
            0.1,
            12.0,
            env_float(env_values, "MAX_ANGULAR_SPEED", 9.0),
            0.1,
        )
    with col3:
        motor_rpm = st.number_input(
            "单轮最大 RPM",
            50.0,
            900.0,
            env_float(env_values, "MAX_MOTOR_RPM", 300.0),
            10.0,
        )
        lateral_direction = st.selectbox(
            "横移硬件方向",
            options=[1, -1],
            index=0
            if int(env_float(env_values, "MECANUM_LATERAL_DIRECTION", 1)) == 1
            else 1,
        )
        theoretical_speed = motor_rpm * math.pi * 0.1016 / 60.0
        st.metric("RPM 对应理论轮缘速度", f"{theoretical_speed:.2f} m/s")

    st.subheader("加速度")
    acc1, acc2, acc3 = st.columns(3)
    with acc1:
        accel_x = st.number_input(
            "前后加速度 (m/s²)", 0.1, 6.0, float(mppi["ax_max"]), 0.1
        )
    with acc2:
        accel_y = st.number_input(
            "横移加速度 (m/s²)", 0.1, 6.0, float(mppi["ay_max"]), 0.1
        )
    with acc3:
        accel_w = st.number_input(
            "旋转加速度 (rad/s²)", 0.1, 15.0, float(mppi["az_max"]), 0.1
        )

    if max(nav_forward, nav_lateral) > theoretical_speed:
        st.warning("导航限速高于当前 RPM 的理论轮缘速度，实际速度会被电机 RPM 限制截断。")

with tab_frequency:
    freq1, freq2, freq3 = st.columns(3)
    with freq1:
        controller_hz = st.number_input(
            "Nav2 控制器 (Hz)", 5.0, 60.0, float(controller["controller_frequency"]), 1.0
        )
        smoother_hz = st.number_input(
            "速度平滑器 (Hz)", 10.0, 100.0, float(smoother["smoothing_frequency"]), 5.0
        )
        cmd_hz = st.number_input(
            "底盘发令 (Hz)",
            10.0,
            100.0,
            env_float(env_values, "CMD_FREQ", 50.0),
            5.0,
        )
    with freq2:
        lidar_hz = st.number_input(
            "雷达扫描目标 (Hz)",
            5.0,
            15.0,
            env_float(env_values, "LIDAR_SCAN_FREQUENCY", 12.0),
            1.0,
        )
        local_update_hz = st.number_input(
            "局部代价地图更新 (Hz)",
            2.0,
            30.0,
            float(local_costmap["update_frequency"]),
            1.0,
        )
        local_publish_hz = st.number_input(
            "局部代价地图发布 (Hz)",
            1.0,
            20.0,
            float(local_costmap["publish_frequency"]),
            1.0,
        )
    with freq3:
        global_update_hz = st.number_input(
            "全局代价地图更新 (Hz)",
            0.5,
            10.0,
            float(global_costmap["update_frequency"]),
            0.5,
        )
        map_publish_hz = st.number_input(
            "地图发布 (Hz)",
            1.0,
            20.0,
            env_float(env_values, "MAP_PUBLISH_FREQUENCY", 12.0),
            1.0,
        )
        slam_update_interval = st.number_input(
            "SLAM 地图更新间隔 (s)",
            0.04,
            1.0,
            env_float(env_values, "SLAM_MAP_UPDATE_INTERVAL", 0.08),
            0.01,
            format="%.2f",
        )
    st.info("IMU 当前为 100 Hz，已经高于导航控制频率，因此不在这里继续提高。")

with tab_manual:
    pad1, pad2, pad3 = st.columns(3)
    with pad1:
        pad_forward = st.number_input(
            "普通前进 (m/s)", 0.05, 2.0, float(teleop["scale_forward"]), 0.05
        )
        pad_turbo_forward = st.number_input(
            "加速前进 (m/s)", 0.05, 2.5, float(teleop["turbo_scale_forward"]), 0.05
        )
    with pad2:
        pad_lateral = st.number_input(
            "普通横移 (m/s)", 0.05, 1.5, float(teleop["scale_lateral"]), 0.05
        )
        pad_turbo_lateral = st.number_input(
            "加速横移 (m/s)", 0.05, 2.0, float(teleop["turbo_scale_lateral"]), 0.05
        )
    with pad3:
        pad_yaw = st.number_input(
            "普通旋转 (rad/s)", 0.1, 6.0, float(teleop["scale_yaw"]), 0.1
        )
        pad_turbo_yaw = st.number_input(
            "加速旋转 (rad/s)", 0.1, 8.0, float(teleop["turbo_scale_yaw"]), 0.1
        )
        pad_hz = st.number_input(
            "手柄发布 (Hz)", 10.0, 100.0, float(teleop["publish_rate"]), 5.0
        )


def save_configuration() -> None:
    backup(ENV_FILE)
    backup(NAV_FILE)
    backup(GAMEPAD_FILE)

    mppi["vx_max"] = float(nav_forward)
    mppi["vx_min"] = -float(nav_reverse)
    mppi["vy_max"] = float(nav_lateral)
    mppi["wz_max"] = float(nav_angular)
    mppi["ax_max"] = float(accel_x)
    mppi["ax_min"] = -float(accel_x)
    mppi["ay_max"] = float(accel_y)
    mppi["ay_min"] = -float(accel_y)
    mppi["az_max"] = float(accel_w)

    controller["controller_frequency"] = float(controller_hz)
    smoother["smoothing_frequency"] = float(smoother_hz)
    smoother["max_velocity"] = [
        float(nav_forward),
        float(nav_lateral),
        float(nav_angular),
    ]
    smoother["min_velocity"] = [
        -float(nav_reverse),
        -float(nav_lateral),
        -float(nav_angular),
    ]
    smoother["max_accel"] = [float(accel_x), float(accel_y), float(accel_w)]
    smoother["max_decel"] = [-float(accel_x), -float(accel_y), -float(accel_w)]
    local_costmap["update_frequency"] = float(local_update_hz)
    local_costmap["publish_frequency"] = float(local_publish_hz)
    global_costmap["update_frequency"] = float(global_update_hz)

    joy["autorepeat_rate"] = float(pad_hz)
    teleop["scale_forward"] = float(pad_forward)
    teleop["scale_lateral"] = float(pad_lateral)
    teleop["scale_yaw"] = float(pad_yaw)
    teleop["turbo_scale_forward"] = float(pad_turbo_forward)
    teleop["turbo_scale_lateral"] = float(pad_turbo_lateral)
    teleop["turbo_scale_yaw"] = float(pad_turbo_yaw)
    teleop["publish_rate"] = float(pad_hz)

    runtime = {
        "MAX_LINEAR_SPEED": f"{driver_linear:.2f}",
        "MAX_ANGULAR_SPEED": f"{driver_angular:.2f}",
        "MAX_MOTOR_RPM": f"{motor_rpm:.1f}",
        "CMD_FREQ": f"{cmd_hz:.1f}",
        "TIMEOUT": "0.30",
        "LOW_CPU_NAV": "1",
        "FEEDBACK_FREQ": "30.0",
        "LIDAR_SCAN_FREQUENCY": f"{lidar_hz:.1f}",
        "SCAN_PUBLISH_FREQUENCY": "0.0",
        "MAP_PUBLISH_FREQUENCY": f"{map_publish_hz:.1f}",
        "SLAM_MAP_UPDATE_INTERVAL": f"{slam_update_interval:.2f}",
        "HEADING_PID_MAX_WZ": "0.30",
        "AUTO_LOCALIZER_MAX_ROTATION_SPEED": "0.45",
        "AUTO_LOCALIZER_ESCAPE_SPEED": "0.24",
        "AUTO_LOCALIZER_ESCAPE_LATERAL_DIRECTION": "1.0",
        "MISSION_ZERO_VELOCITY_HZ": "30.0",
        "MECANUM_LATERAL_DIRECTION": str(lateral_direction),
        "NAV_START_DELAY": "8.0",
        "NAV_NODE_BATCH_DELAY": "2.0",
        "MISSION_START_DELAY": "20.0",
        "LIFECYCLE_STABILITY_WINDOW": "5",
    }

    write_yaml_atomic(NAV_FILE, nav)
    write_yaml_atomic(GAMEPAD_FILE, gamepad)
    write_env_atomic(ENV_FILE, runtime)


st.divider()
left, right = st.columns(2)
with left:
    if st.button("保存参数", type="secondary", use_container_width=True):
        save_configuration()
        st.success("参数已保存，当前运行中的 ROS 节点尚未重启。")
with right:
    if st.button("保存并重启导航", type="primary", use_container_width=True):
        save_configuration()
        fallback_map = floor_default_map(building, configured_floor, map_files)
        restart_ok, restart_message = restart_navigation(
            fallback_map, configured_floor, False
        )
        if restart_ok:
            st.success(f"{restart_message} Foxglove 保持运行。")
        else:
            st.error(restart_message)

with st.expander("文件与日志"):
    st.code(
        "\n".join(
            [
                f"运行参数: {ENV_FILE}",
                f"Nav2 参数: {NAV_FILE}",
                f"手柄参数: {GAMEPAD_FILE}",
                f"重启日志: {UI_LOG}",
                f"地图保存日志: {MAP_SAVE_LOG}",
            ]
        )
    )
