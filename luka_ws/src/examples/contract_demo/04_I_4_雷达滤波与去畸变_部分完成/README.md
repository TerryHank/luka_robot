# 04 I-4 雷达滤波与去畸变

合同对应状态：**部分完成**

当前主要数据是二维LaserScan，不是完整3D点云；去畸变演示输出独立话题。

## 启动及观察

    cd "/home/sunrise/luka_ws/src/examples/contract_demo/04_I_4_雷达滤波与去畸变_部分完成"
    ./demo.sh

实时打印上下雷达、融合扫描和去畸变扫描的有效点数、最近距离及时间戳。Foxglove查看对应LaserScan。

- ./check.sh：查看launch参数，不启动设备。
- ./demo.sh start_hardware:=false：仅回放/隔离监视，不能作为硬件验收。
- Ctrl+C 或另一个终端 ./stop.sh：停止本launch创建的进程，保留复用的运行服务。
- 按序演示时先结束上一项。完整已有栈可以复用；部分栈/重复串口/SLAM-AMCL冲突会拒绝启动。
- Foxglove连接 ws://192.168.3.150:8765。页面 http://192.168.3.150:8503/。
- 空闲状态、无目标、缺设备时如实显示WAITING；STALE/INVALID不是验收通过。
- 本次验证不发送实车运动目标；真实运动/避障/返航效果仍需现场验收。

## 代码证据

- /home/sunrise/luka_ws/src/control/ddsm_car_control/ddsm_car_control/dual_laser_fusion.py
- /home/sunrise/luka_ws/src/control/ddsm_car_control/ddsm_car_control/laser_scan_deskewer.py
