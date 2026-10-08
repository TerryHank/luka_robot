#!/usr/bin/env python3
"""Native Foxglove case launch services; startup alone starts no hardware.

Only manifest-listed entrypoints can run. Own child processes are stopped;
existing hardware and production services are never killed to resolve conflicts.
"""
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

import rclpy
from rclpy.node import Node
from rcl_interfaces.msg import SetParametersResult
from nav_msgs.msg import Odometry
from std_msgs.msg import String
from std_srvs.srv import Empty, SetBool, Trigger

HERE = Path(__file__).resolve().parent
DATA = Path.home() / "luka_data"


class CaseEngine:
    def __init__(self, items, data=DATA, here=HERE):
        self.items, self.data, self.here = items, data, here
        self.children = []
        self.logs = []
        self.cancel_start = threading.Event()
        self.phase, self.case, self.message = "idle", "", "选择案例，点击开始；启动不发送运动目标"

    def map_choices(self):
        return sorted(str(p) for p in (self.data / "maps").rglob("*.yaml") if p.is_file())

    def validate_map(self, value):
        path = Path(value).resolve()
        if not path.is_relative_to((self.data / "maps").resolve()) or not path.is_file() or path.suffix != ".yaml":
            raise ValueError("地图必须是 luka_data/maps 内已有的 YAML 文件")
        return path

    def start_process(self, number, options=()):
        if self.cancel_start.is_set():
            raise InterruptedError("操作者请求停止")
        item = self.items[number]
        if item["profile"] in {"missing", "service"}:
            raise ValueError(item["limitation"])
        log_dir = self.data / "recordings/contract_demo/gui_logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log = log_dir / (number + "_" + str(time.time_ns()) + ".log")
        with log.open("w") as output:
            proc = subprocess.Popen([sys.executable, str(self.here / "runner.py"), "--item", number, *options],
                stdout=output, stderr=subprocess.STDOUT, start_new_session=True,
                env={**os.environ, "PYTHONUNBUFFERED": "1", "FOXGLOVE_GUI_LAUNCH": "1"})
        self.children.append((number, proc, log))
        self.logs.append(str(log))
        return proc

    def log_tail(self):
        parts = []
        for _, _, path in self.children:
            if path.exists():
                with path.open("rb") as log:
                    log.seek(max(0, path.stat().st_size-2000))
                    parts.append(log.read().decode(errors="replace"))
        return "\n".join(parts)[-4000:]

    def existing_base(self):
        p = subprocess.run(["ros2", "node", "list"], text=True, capture_output=True, timeout=10)
        return {"/nx_imu", "/nx_upper_lidar", "/nx_lower_lidar", "/zdt_mecanum_rs485_bridge"} <= set(p.stdout.splitlines())

    def start(self, number, with_ekf=False, map_yaml=""):
        if number not in self.items or self.items[number]["profile"] in {"missing", "service"}:
            raise ValueError("本项目尚无可运行实现／属于服务履约，请查看本案例缺口")
        if self.children:
            raise RuntimeError("先点击停止案例，确认停止后再切换")
        options = []
        if with_ekf:
            if number != "03":
                raise ValueError("融合仅适用于03")
            options += ["--with-ekf"]
        if number == "10" and map_yaml:
            options += ["--map-yaml", str(self.validate_map(map_yaml))]
        self.phase, self.case, self.message = "starting", number, "正在启动，等待节点及数据；没有运动目标"
        self.logs = []
        # Mapping and fused IMU can be demonstrated without a separate CLI base session.
        if (number in {"04", "09"} or with_ekf) and not self.existing_base():
            base = self.start_process("01")
            deadline = time.monotonic() + 25
            while not self.existing_base():
                if self.cancel_start.is_set():
                    raise InterruptedError("操作者请求停止")
                if base.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError("底盘/传感器未就绪；停止案例后查看界面日志")
                time.sleep(.2)
        self.start_process(number, options)
        # Wait for the existing launch ownership record, not a fixed startup delay.
        item = self.items[number]
        if "launch" in item:
            group = item.get("launch_group", "drive_odom" if number in {"01", "02"} else "imu_axes")
            deadline = time.monotonic() + 15
            proc = self.children[-1][1]
            record = self.data / "recordings/contract_demo" / (group + ".pid.json")
            while True:
                if self.cancel_start.is_set():
                    raise InterruptedError("操作者请求停止")
                if proc.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError("ROS launch 未就绪；查看界面日志，点击停止清理")
                if record.exists():
                    try:
                        owner = json.loads(record.read_text())
                    except json.JSONDecodeError:
                        owner = {}
                    if owner.get("pid") == proc.pid:
                        break
                    if owner.get("pid") and Path("/proc/%s" % owner["pid"]).exists():
                        raise RuntimeError("已有其他启动所有者；拒绝接管")
                time.sleep(.1)
        self.phase, self.message = "running", "入口已启动；以实际消息、反馈和实测结果验收"

    def stop(self):
        self.phase = "stopping"
        # Reap child launches in reverse dependency order, never signal an external PID.
        while self.children:
            _, proc, _ = self.children[-1]
            if proc.poll() is None:
                proc.send_signal(signal.SIGINT)
                proc.wait(timeout=25)
            self.children.pop()
        self.phase, self.case, self.message = "idle", "", "本管理器启动的案例已停止；借用的生产服务保留"


class GuiLauncher(Node):
    def __init__(self, engine=None):
        super().__init__("contract_demo_launcher")
        items = json.loads((HERE.parent / "manifest.json").read_text())["items"] if engine is None else []
        self.engine = engine or CaseEngine({i["number"]: i for i in items})
        state_dir = self.engine.data / "recordings/contract_demo"
        state_dir.mkdir(parents=True, exist_ok=True)
        self.lock = (state_dir / "gui_launcher.lock").open("a")
        fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.busy = False
        self.worker = None
        self.odom = None
        self.odom_at = 0.
        self.create_subscription(Odometry, "/wheel/odom", self.on_odom, 10)
        self.pause = self.create_client(Empty, "/base_control/pause_now")
        self.disable = self.create_client(SetBool, "/nx/navigation_enable")
        self.status = self.create_publisher(String, "/contract_demo/gui/status", 10)
        self.declare_parameter("map_yaml", str(self.engine.data / "maps/ddsm_map_floor_4.yaml"))
        self.add_on_set_parameters_callback(self.parameters)
        self.create_service(Trigger, "/contract_demo/gui/stop", self.stop)
        for number in self.engine.items:
            self.create_service(Trigger, "/contract_demo/gui/start/" + number,
                lambda request, response, n=number: self.start(n, False, response))
        self.create_service(Trigger, "/contract_demo/gui/start/03_ekf",
            lambda request, response: self.start("03", True, response))
        self.maps = self.engine.map_choices()
        self.create_timer(.5, self.tick)

    def parameters(self, values):
        try:
            for value in values:
                if value.name != "map_yaml":
                    raise ValueError("不支持的参数")
                self.engine.validate_map(value.value)
            return SetParametersResult(successful=True)
        except (ValueError, TypeError) as error:
            return SetParametersResult(successful=False, reason=str(error))

    def on_odom(self, message):
        self.odom, self.odom_at = message.twist.twist, time.monotonic()

    def submit(self, action, response):
        if self.busy:
            response.success, response.message = False, "启动／停止正在进行；查看状态后重试"
            return response
        self.busy = True
        def work():
            try:
                action()
            except Exception as error:
                self.engine.phase, self.engine.message = "error", str(error)
            finally:
                if self.engine.cancel_start.is_set():
                    try:
                        self.stop_owned()
                    except Exception as error:
                        self.engine.phase, self.engine.message = "error", str(error)
                self.busy = False
        self.worker = threading.Thread(target=work)
        self.worker.start()
        response.success, response.message = True, "请求已接受；等待 GUI 状态和真实数据"
        return response

    def start(self, number, with_ekf, response):
        if number not in self.engine.items or self.engine.items[number]["profile"] in {"missing", "service"}:
            response.success, response.message = False, "缺少实现／服务履约项；只能核对缺口和资料"
            return response
        if not self.busy:
            self.engine.cancel_start.clear()
        return self.submit(lambda: self.engine.start(number, with_ekf, self.get_parameter("map_yaml").value), response)

    def stop(self, _request, response):
        if self.busy:
            self.engine.cancel_start.set()
            response.success, response.message = True, "停止已请求；等待启动中止与停稳确认"
            return response
        return self.submit(self.stop_owned, response)

    def stop_owned(self):
        if self.engine.children:
            futures = []
            if self.disable.service_is_ready():
                futures.append(self.disable.call_async(SetBool.Request(data=False)))
            if self.pause.service_is_ready():
                futures.append(self.pause.call_async(Empty.Request()))
            deadline = time.monotonic()+3
            while futures and not all(f.done() for f in futures):
                if time.monotonic() > deadline:
                    raise RuntimeError("停止服务未确认；保留当前进程以便重试")
                time.sleep(.05)
            if futures:
                for future in futures:
                    future.result()
                # Consecutive fresh measured samples confirm stopping, never inferred from commands.
                stable, last_sample = 0, 0.
                deadline = time.monotonic()+3
                while stable < 3:
                    if self.odom_at != last_sample:
                        last_sample = self.odom_at
                        v = self.odom
                        stable = stable+1 if v and time.monotonic()-self.odom_at < .6 and \
                            abs(v.linear.x)<.02 and abs(v.linear.y)<.02 and abs(v.angular.z)<.03 else 0
                    if time.monotonic() > deadline:
                        raise RuntimeError("新鲜轮速未确认停稳；点击停止重试，禁止切换")
                    time.sleep(.05)
        self.engine.stop()
        self.maps = self.engine.map_choices()

    def tick(self):
        if not self.busy and self.engine.phase == "running":
            ended = [(n, p.poll()) for n, p, _ in self.engine.children if p.poll() is not None]
            if ended:
                expected = all("launch" not in self.engine.items[n] and code == 0 for n, code in ended)
                self.engine.phase = "reviewed" if expected else "error"
                self.engine.message = "资料检查已结束，请核对输出" if expected else "案例进程已退出，请停止清理并查看日志"
        self.status.publish(String(data=json.dumps(dict(
            phase=self.engine.phase, case=self.engine.case, busy=self.busy, message=self.engine.message,
            log=self.engine.log_tail(), log_files=self.engine.logs, maps=self.maps), ensure_ascii=False)))


def main():
    from rclpy.signals import SignalHandlerOptions
    rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
    node = GuiLauncher()
    def interrupt(_signal, _frame):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGINT, interrupt)
    signal.signal(signal.SIGTERM, interrupt)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.engine.cancel_start.set()
        while node.worker and node.worker.is_alive():
            rclpy.spin_once(node, timeout_sec=.05)
        cleanup = threading.Thread(target=node.stop_owned)
        cleanup.start()
        while cleanup.is_alive():
            rclpy.spin_once(node, timeout_sec=.05)
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
