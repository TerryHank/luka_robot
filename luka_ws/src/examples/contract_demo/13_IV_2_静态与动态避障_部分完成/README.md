# 13 IV-2 静态与动态避障

合同对应状态：**部分完成**

代价地图/CollisionMonitor存在；动态行人实时避障完整闭环仍需现场验收。

## 启动及观察

    cd "/home/sunrise/luka_ws/src/examples/contract_demo/13_IV_2_静态与动态避障_部分完成"
    ./demo.sh

启动同一Nav2安全链，实时打印融合扫描最近距离、碰撞监视状态、底盘安全门和导航状态。动态行人闭环效果仍待现场验收。

- ./check.sh：查看launch参数，不启动设备。
- ./demo.sh start_hardware:=false：仅回放/隔离监视，不能作为硬件验收。
- Ctrl+C 或另一个终端 ./stop.sh：停止本launch创建的进程，保留复用的运行服务。
- 按序演示时先结束上一项。完整已有栈可以复用；部分栈/重复串口/SLAM-AMCL冲突会拒绝启动。
- Foxglove连接 ws://192.168.3.150:8765。页面 http://192.168.3.150:8503/。
- 空闲状态、无目标、缺设备时如实显示WAITING；STALE/INVALID不是验收通过。
- 本次验证不发送实车运动目标；真实运动/避障/返航效果仍需现场验收。

## 代码证据

- /home/sunrise/luka_ws/src/common/config/nx_nav2.yaml
- /home/sunrise/luka_ws/src/control/ddsm_car_control/ddsm_car_control/lateral_escape_guard.py
