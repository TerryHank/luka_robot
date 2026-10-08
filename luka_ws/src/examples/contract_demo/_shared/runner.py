#!/usr/bin/env python3
"""Contract demo startup only; no motion goals or velocity commands."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import urlopen

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
WS = HERE.parents[3]
SRC = WS / "src"
DATA = WS.parent / "luka_data"
STATE_DIR = DATA / "recordings/contract_demo"
MANIFEST = json.loads((BASE / "manifest.json").read_text())
ITEMS = {i["number"]: i for i in MANIFEST["items"]}
BRIDGE = "luka-ws-foxglove-bridge.service"
SENSORS = "luka-ws-hardware@sensors.service"
LOCALIZATION = "luka-ws-hardware@localization.service"
NAV = "luka-ws-hardware@navigation.service"
DASH = "luka-ws-dashboard.service"
ODOM = "luka-contract-odom.service"
LOC = "luka-contract-localization.service"
SLAM = "luka-contract-slam.service"
BUSINESS = "luka-contract-business.service"
EKF = "luka-contract-ekf.service"
DESKEW = "luka-contract-deskew.service"
FACE = "luka-contract-face.service"
TOPICS = {
    "drive_odom": ["/wheel/odom"], "imu_launch": ["/imu/data", "/contract_demo/odometry/filtered"],
    "kinematics": ["/wheel/odom"], "imu": ["/imu/data", "/contract_demo/odometry/filtered"],
    "lidar": ["/scan", "/scan_low_filtered", "/contract_demo/scan_deskewed"],
    "camera": ["/camera/color/image_raw", "/camera/depth/image_raw"],
    "slam": ["/map"], "map": ["/map"], "localization": ["/amcl_pose"],
    "navigation": ["/plan"], "avoidance": ["/collision_monitor_state"],
    "business": ["/patrol/status", "/home/status"], "home": ["/home/status"],
    "smoothing": ["/nx/nav_smoothed"], "state_machine": ["/hotel/mission/status"],
    "face": ["/contract_demo/face_image"], "voice": ["/voice/doa"],
}


def run(argv, timeout=30, capture=True):
    return subprocess.run(argv, timeout=timeout, text=True,
                          capture_output=capture, check=False)


def active(unit):
    return run(["systemctl", "is-active", "--quiet", unit]).returncode == 0


def ros_nodes():
    p = run(["ros2", "node", "list"], timeout=10)
    if p.returncode:
        raise RuntimeError("ROS 节点查询失败：" + p.stderr[-300:])
    return set(p.stdout.splitlines())


def units_for(profile, nodes=()):
    base = [BRIDGE, SENSORS]
    odom = [] if (active("luka-ws-hardware@manual_base.service") or
                  active(LOCALIZATION) or ("/nx_readonly_wheel_odom" in nodes and
                                          not active(ODOM))) else [ODOM]
    loc = [] if active(LOCALIZATION) else [LOC]
    nav = base + odom + loc + [NAV]
    profiles = {
        "protocol": [], "environment": [], "interfaces": [], "documentation": [], "delivery": [],
        "kinematics": base + odom, "imu": base + odom + [EKF],
        "lidar": base + odom + [DESKEW], "camera": [BRIDGE, "luka-ws-orbbec-camera.service"],
        "layers": nav + ["luka-ws-orbbec-camera.service", DASH],
        "slam": base + odom + [SLAM], "map": base + odom + loc,
        "localization": base + odom + loc + [DASH], "navigation": nav + [DASH],
        "avoidance": nav + [DASH], "smoothing": nav,
        "business": nav + [BUSINESS, DASH], "home": nav + [BUSINESS, DASH],
        "state_machine": nav + [BUSINESS, DASH], "diagnostics": [BRIDGE, DASH],
        "voice": [DASH, "luka-ws-chat.service", "luka-ws-agent.service",
                  "luka-ws-hardware@voice.service", "luka-ws-xiaozhi.service"],
        "face": [BRIDGE, "luka-ws-orbbec-camera.service", FACE],
    }
    return list(dict.fromkeys(profiles.get(profile, [])))


def check(item):
    missing = [p for p in item["evidence"] if not (SRC / p).exists()]
    if missing:
        raise RuntimeError("源码证据缺失：" + ", ".join(missing))
    return {"number": item["number"], "clause": item["clause"],
            "status": item["status"], "entry_structure": (
                "PASS_STATIC" if item["evidence"] else "NO_EXECUTABLE_IMPLEMENTATION"),
            "live_validation": "PENDING", "limitation": item["limitation"]}


def guard(profile, units, nodes):
    if not units:
        return
    foreign = run(["systemctl", "list-units", "--all", "--no-legend", "--plain",
                   "luka-s100-*"]).stdout
    if any(len(l.split()) > 3 and l.split()[2] in ("active", "activating")
           for l in foreign.splitlines()):
        raise RuntimeError("旧 luka-s100 栈正在运行；演示不能重复占用设备。")
    if SLAM in units and (active(LOCALIZATION) or active(LOC) or active(NAV) or
                          "/amcl" in nodes or "/map_server" in nodes):
        raise RuntimeError("已有定位/导航地图发布者；先停止对应演示，再启动 SLAM。")
    if LOC in units and (active(SLAM) or "/slam_toolbox" in nodes):
        raise RuntimeError("SLAM 正在发布地图/TF；先停止建图演示，再加载静态地图。")
    if LOC in units and not active(LOC) and {"/amcl", "/map_server"} & set(nodes):
        raise RuntimeError("检测到非演示管理的 AMCL/map_server，拒绝重复启动。")
    if BUSINESS in units and not active(BUSINESS):
        owners = {"/ddsm_home_manager", "/ddsm_patrol_manager", "/ddsm_mission_control"}
        if owners & set(nodes):
            raise RuntimeError("已有任务/Home/巡航节点，拒绝创建重复任务所有者。")
    if ODOM in units and not active(ODOM):
        p = run(["fuser", "/dev/nx_base"])
        if p.returncode == 0:
            raise RuntimeError("底盘串口已有进程占用，拒绝再启动只读里程计。")
    if profile == "voice":
        cfg = SRC / "common/legacy/audio.env"
        text = cfg.read_text() if cfg.exists() else ""
        if "NX_MIC=" not in text or "NX_SPEAKER=" not in text:
            raise RuntimeError("请在 src/common/config/audio.env 配置 NX_MIC 和 NX_SPEAKER。")


def install_aux(units):
    changed = False
    for unit in units:
        if not unit.startswith("luka-contract-"):
            continue
        source = HERE / "units" / unit
        destination = Path("/etc/systemd/system") / unit
        if destination.exists() and destination.read_bytes() == source.read_bytes():
            continue
        if active(unit):
            raise RuntimeError(unit + " 正在运行，不能替换其启动定义。")
        p = run(["sudo", "-n", "install", "-m", "0644", str(source), str(destination)])
        if p.returncode:
            raise RuntimeError(p.stderr[-300:])
        changed = True
    if changed:
        p = run(["sudo", "-n", "systemctl", "daemon-reload"])
        if p.returncode:
            raise RuntimeError(p.stderr[-300:])


def read_state():
    path = STATE_DIR / "launcher_state.json"
    return json.loads(path.read_text()) if path.exists() else {"demos": {}, "managed": []}


def write_state(state):
    path = STATE_DIR / "launcher_state.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    tmp.replace(path)


def release(number, state):
    state["demos"].pop(number, None)
    needed = {u for units in state["demos"].values() for u in units}
    failures = []
    for unit in list(reversed(state["managed"])):
        if unit in needed:
            continue
        p = run(["sudo", "-n", "systemctl", "stop", unit], timeout=60)
        if p.returncode:
            failures.append(unit)
        else:
            state["managed"].remove(unit)
    write_state(state)
    if failures:
        raise RuntimeError("停止未确认：" + ", ".join(failures))


def start(item):
    profile = item["profile"]
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with (STATE_DIR / "launcher.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = read_state()
        nodes = ros_nodes() if units_for(profile) else ()
        units = units_for(profile, nodes)
        planned = {u for number, existing in state["demos"].items()
                   if number != item["number"] for u in existing}
        if SLAM in units and planned & {LOC, LOCALIZATION, NAV}:
            raise RuntimeError("其他演示仍引用定位/导航；先运行其 stop.sh。")
        if LOC in units and SLAM in planned:
            raise RuntimeError("其他演示仍引用 SLAM；先运行其 stop.sh。")
        guard(profile, units, nodes)
        install_aux(units)
        state["demos"][item["number"]] = units
        write_state(state)
        for unit in units:
            if active(unit):
                continue
            if unit not in state["managed"]:
                state["managed"].append(unit)
                write_state(state)
            print("启动", unit, flush=True)
            p = run(["sudo", "-n", "systemctl", "start", unit], timeout=80)
            if p.returncode or not active(unit):
                raise RuntimeError(unit + " 未启动成功；使用本条 stop.sh 清理。\n" + p.stderr[-300:])
    if profile in ("protocol", "kinematics", "environment", "interfaces",
                   "documentation", "delivery", "smoothing"):
        p = run([sys.executable, str(HERE / "offline_demo.py"), profile], capture=False)
        if p.returncode:
            raise RuntimeError("离线演示失败")
    if profile == "camera":
        for topic in TOPICS["camera"]:
            print("等待相机消息：", topic, flush=True)
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                try:
                    p = run(["ros2", "topic", "echo", topic, "--once", "--field", "header",
                             "--qos-reliability", "best_effort"], timeout=5)
                    if p.returncode == 0 and p.stdout.strip():
                        print(p.stdout.strip())
                        break
                except subprocess.TimeoutExpired:
                    pass
                time.sleep(.5)
            else:
                raise RuntimeError(topic + " 未收到相机消息；查看相机日志后运行 stop.sh。")
    status(item)


def status(item):
    print(item["number"], item["clause"], item["title"], item["status"])
    print("对应范围：", item["limitation"])
    if "launch" in item:
        group = item.get("launch_group", "drive_odom" if item["profile"]=="drive_odom" else "imu_axes")
        path = STATE_DIR / (group + ".pid.json")
        record = json.loads(path.read_text()) if path.exists() else {}
        running = record.get("pid") and Path("/proc/%s" % record["pid"]).exists()
        print("ROS launch", group, "running" if running else "not running")
    else:
        for unit in units_for(item["profile"]):
            print(unit, "active" if active(unit) else "未启动")
    for topic in TOPICS.get(item["profile"], []):
        p = run(["ros2", "topic", "info", topic], timeout=10)
        print(topic, p.stdout.strip() if p.returncode == 0 else "尚无数据/话题")
    if item["profile"] in ("business", "home", "state_machine", "diagnostics", "voice", "layers"):
        print("操作/诊断页面：http://192.168.3.150:8503/")
    if TOPICS.get(item["profile"]):
        print("Foxglove：ws://192.168.3.150:8765；查看上方话题。")
    if "launch" in item or units_for(item["profile"]):
        print("启动成功只证明节点已运行；实时数据和合同完整闭环仍须按 README 验证。")
    else:
        print("本入口是离线/资料演示，不代表硬件或完整交付已验收。")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--item")
    parser.add_argument("--with-ekf",action="store_true")
    parser.add_argument("--map-yaml")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--plan", action="store_true")
    modes.add_argument("--status", action="store_true")
    modes.add_argument("--stop", action="store_true")
    modes.add_argument("--check-all", action="store_true")
    modes.add_argument("--stop-all", action="store_true")
    modes.add_argument("--list", action="store_true")
    args = parser.parse_args()
    if args.list:
        for item in ITEMS.values():
            print(item["number"], item["clause"], item["title"], item["status"])
        return
    if args.check_all:
        results = [check(i) for i in ITEMS.values()]
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return
    if args.stop_all:
        groups = {i.get("launch_group", "drive_odom" if i["profile"]=="drive_odom" else "imu_axes")
                  for i in ITEMS.values() if "launch" in i}
        for group in sorted(groups):
            p = run([sys.executable, str(HERE/"stop_launch.py"), group], capture=False)
            if p.returncode: raise RuntimeError("launch shutdown not confirmed: " + group)
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with (STATE_DIR / "launcher.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            state = read_state()
            for number in list(state["demos"]):
                release(number, state)
            release("__orphan_cleanup__", state)
        return
    if not args.item or args.item.zfill(2) not in ITEMS:
        parser.error("需要 --item 01 至 27")
    item = ITEMS[args.item.zfill(2)]
    if args.map_yaml and item["number"]!="10":
        parser.error("--map-yaml is only valid for item10")
    if args.with_ekf and item["number"]!="03":
        parser.error("--with-ekf is only valid for item03")

    if args.check:
        print(json.dumps(check(item), ensure_ascii=False, indent=2))
    elif args.plan and "launch" in item:
        print(json.dumps({"item": item["number"], "launch": str(BASE / item["folder"] / "demo.launch.py"), "keyboard_topic": "/nx/web_teleop_cmd_vel" if item["profile"]=="drive_odom" else None}, ensure_ascii=False, indent=2))
    elif args.plan:
        print(json.dumps({"item": item["number"], "profile": item["profile"],
                          "units": units_for(item["profile"]),
                          "sends_motion_goal": False, "publishes_velocity": False},
                         ensure_ascii=False, indent=2))
    elif args.stop and "launch" in item:
        group=item.get("launch_group", "drive_odom" if item["profile"]=="drive_odom" else "imu_axes")
        p=run([sys.executable,str(HERE/"stop_launch.py"),group],capture=False)
        if p.returncode:raise RuntimeError("launch停止未确认")
    elif args.stop:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with (STATE_DIR / "launcher.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            release(item["number"], read_state())
    elif args.status:
        status(item)
    elif item["profile"] in ("missing", "service"):
        print(item["clause"], item["status"], item["limitation"], file=sys.stderr)
        raise SystemExit(3)
    else:
        check(item)
        if "launch" in item:
            os.execvp("ros2",["ros2","launch",str(BASE/item["folder"]/"demo.launch.py")] +
                      (["with_ekf:=true"] if args.with_ekf else []) +
                      (["map_yaml:="+args.map_yaml] if args.map_yaml else []))
        start(item)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        print("演示未就绪：" + str(error), file=sys.stderr)
        raise SystemExit(1)
