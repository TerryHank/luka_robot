"""Preflight and process bookkeeping for foreground ROS launch demos."""
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
WS = HERE.parents[3]
SRC = WS / "src"
STATE = WS.parent / "luka_data/recordings/contract_demo"
LOCKS = []


def enabled(value):
    if value.lower() not in ("true", "false"):
        raise ValueError("Boolean launch arguments must be true or false")
    return value.lower() == "true"


def active(unit):
    return subprocess.run(["systemctl", "is-active", "--quiet", unit]).returncode == 0


def nodes():
    p = subprocess.run(["ros2", "node", "list"], capture_output=True, text=True, timeout=10)
    if p.returncode:
        raise RuntimeError("ROS graph unavailable: " + p.stderr[-250:])
    return set(p.stdout.splitlines())


def tty_path():
    if not os.isatty(0):
        raise RuntimeError("Keyboard requires an interactive terminal. Use ssh -t or keyboard:=false.")
    return os.ttyname(0)


def keyboard_command(terminal):
    return ["bash", "-c", 'terminal=$1; shift; exec "$@" < "$terminal"',
            "contract-telekey", terminal, "ros2", "run", "teleop_twist_keyboard",
            "teleop_twist_keyboard", "--ros-args", "-r",
            "cmd_vel:=/nx/web_teleop_cmd_vel", "-p", "speed:=0.1", "-p", "turn:=0.2"]


def claim(group, launch_file):
    STATE.mkdir(parents=True, exist_ok=True)
    lock = (STATE / (group + ".lock")).open("a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        raise RuntimeError(group + " launch is already running")
    LOCKS.append(lock)
    pid = os.getpid()
    start = Path(f"/proc/{pid}/stat").read_text().split()[21]
    path = STATE / (group + ".pid.json")
    token = next((a for a in sys.argv if a.endswith(".launch.py") and Path(a).is_file()),
                 str(launch_file))
    path.write_text(json.dumps({"pid": pid, "start_ticks": start, "launch_file": str(launch_file),
                               "launch_token": token}))

    def clear(event, context):
        if path.exists() and json.loads(path.read_text()).get("pid") == pid:
            path.unlink()
        lock.close()
    # Visualization is optional; a disconnected desktop never weakens ROS gates.
    try:
        from foxglove_client import show_layout
        if os.environ.get("FOXGLOVE_GUI_LAUNCH") != "1":
            show_layout(group)
    except (OSError, ValueError, KeyError) as error:
        print("[Foxglove] visualization unavailable: " + str(error), flush=True)
    return clear


def reserve_device(name):
    """Hold a startup ownership lock while this launch owns the hardware."""
    STATE.mkdir(parents=True, exist_ok=True)
    lock = (STATE / (name + ".device.lock")).open("a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        raise RuntimeError(name + " is being started/owned by another demonstration")
    LOCKS.append(lock)
