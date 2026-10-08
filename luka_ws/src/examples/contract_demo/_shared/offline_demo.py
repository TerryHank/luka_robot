#!/usr/bin/env python3
"""Exercise existing pure implementations without opening a motor port."""
import ast
import json
from pathlib import Path
import platform
import subprocess
import sys

WS = Path(__file__).resolve().parents[4]
SRC = WS / "src"
DATA = WS.parent / "luka_data"
sys.path.insert(0, str(SRC / "control/ddsm_car_control"))
sys.path.insert(0, str(SRC / "visualization/console"))
kind = sys.argv[1]

if kind == "protocol":
    from ddsm_car_control.zdt_y42_protocol import build_modbus_read_registers, validate_crc16_modbus
    packet = build_modbus_read_registers(1, 0x0036, 2)
    print("上位机 Modbus 读取帧：", packet.hex(" "))
    print("CRC 校验：", validate_crc16_modbus(packet))
    print("只生成内存中的帧；未打开串口。没有 STM32 固件/CAN 的实现证据。")
elif kind in ("kinematics", "smoothing"):
    from ddsm_car_control.zdt_mecanum_kinematics import (
        MecanumGeometry, twist_to_physical_wheel_rpm, physical_wheel_rpm_to_body_twist,
    )
    geometry = MecanumGeometry()
    for velocity in ((.1, 0., 0.), (0., .1, 0.), (0., 0., .2)):
        rpm = twist_to_physical_wheel_rpm(*velocity, geometry)
        result = physical_wheel_rpm_to_body_twist(rpm, geometry)
        assert all(abs(a - b) < 1e-6 for a, b in zip(velocity, result))
        print(json.dumps({"input_twist": velocity, "wheel_rpm": rpm,
                          "roundtrip_twist": result}, ensure_ascii=False))
    print("实际模型为麦克纳姆，非合同字面的差速。计算结果未发布为速度。")
    if kind == "smoothing":
        print("实时平滑输出由已启动的 velocity_smoother 产生，查看 /nx/nav_smoothed。")
elif kind == "environment":
    from ament_index_python.packages import get_packages_with_prefixes
    packages = {k: v for k, v in get_packages_with_prefixes().items()
                if v.startswith(str(WS / "install"))}
    print(subprocess.check_output(["lsb_release", "-ds"], text=True).strip())
    print("Python", platform.python_version())
    print(json.dumps(packages, ensure_ascii=False, indent=2))
    print("工作区：", WS, "\n运行数据：", DATA)
elif kind in ("interfaces", "documentation"):
    for name in ("ai_msgs/msg/PerceptionTargets", "hotel_semantic_map_msgs/msg/Destination"):
        p = subprocess.run(["ros2", "interface", "show", name], text=True, capture_output=True)
        if p.returncode:
            raise SystemExit(p.stderr)
        print(name, "\n", p.stdout)
    if kind == "documentation":
        tree = ast.parse((SRC / "visualization/console/nx_assistant_tools.py").read_text())
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "TOOLS"
                                                    for t in node.targets):
                print("现有应用工具接口：", json.dumps(ast.literal_eval(node.value),
                                                   ensure_ascii=False, indent=2))
        print("这是现有接口盘点，不是完整合同应用接口规范的交付证明。")
elif kind == "delivery":
    packages = subprocess.check_output(["colcon", "list", "--base-paths", str(SRC)], text=True)
    print(packages)
    print("源码：", SRC)
    print("配置：", SRC / "common/config")
    print("资料：", SRC / "docs")
    print("运行数据：", DATA)
    print("缺失交付物：STM32 固件、经确认的完整应用接口规范；本盘点不代表验收完成。")
else:
    raise SystemExit("未知离线演示类型")
