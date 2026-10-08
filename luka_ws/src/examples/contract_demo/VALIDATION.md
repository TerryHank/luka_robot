# 实时launch演示验证（2026-10-08）

- 27条合同逻辑编号保持，01/02合并为一个实际目录，18个实际launch入口。
- 30项新增回归 + 4项现有去畸变回归通过。
- 18个launch参数检查及入口shell语法检查通过。
- 5项隔离ROS域188的launch消息传输通过：扫描、深度、路径、巡航、碰撞。
- 真实IMU轴数据、RGB-D、双雷达融合及去畸变输出已读取有效消息。
- 相机/雷达launch停止后exit=0、无Traceback、无演示串口残留。
- 01/02键盘只在隔离域188验证；未发送实车运动指令或导航目标。
- Nav2运动、巡航、返航、语音趋近及身份/权限联动仍PENDING_LIVE_VALIDATION。
- colcon发现18个唯一包；工作区根目录检查通过。包发现不等于新增包全量构建通过。

## 重跑静态回归

    source /home/sunrise/luka_ws/src/system/environment.bash
    python3 -m pytest -q /home/sunrise/luka_ws/src/examples/contract_demo/_shared/test_function_launch.py /home/sunrise/luka_ws/src/control/ddsm_car_control/test/test_laser_scan_deskewer.py
    /home/sunrise/luka_ws/src/examples/contract_demo/check_all.sh

每个功能目录./check.sh查看launch参数；./demo.sh为真实设备演示，不属于静态回归。
隔离/回放用start_hardware:=false，并在隔离ROS域内提供录制数据，不向生产传感话题注入模拟数据。

详细JSON与现场日志：/home/sunrise/luka_data/recordings/contract_demo/。
