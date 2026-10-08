# 12 IV-1 全局局部路径规划

合同对应状态：**代码已完成_待现场验收**

启动现有Nav2规划/控制后端；不会自动发目标，现场调优和运动效果未验收。

## 启动及观察

    cd "/home/sunrise/luka_ws/src/examples/contract_demo/12_IV_1_全局局部路径规划_代码已完成_待现场验收"
    ./demo.sh

启动保护底盘、传感器、AMCL及Nav2，现有页面手动选择导航目标；打印/plan路径点数和/hotel/navigation_status。启动不自动下发目标。

- ./check.sh：查看launch参数，不启动设备。
- ./demo.sh start_hardware:=false：仅回放/隔离监视，不能作为硬件验收。
- Ctrl+C 或另一个终端 ./stop.sh：停止本launch创建的进程，保留复用的运行服务。
- 按序演示时先结束上一项。完整已有栈可以复用；部分栈/重复串口/SLAM-AMCL冲突会拒绝启动。
- Foxglove连接 ws://192.168.3.150:8765。页面 http://192.168.3.150:8503/。
- 空闲状态、无目标、缺设备时如实显示WAITING；STALE/INVALID不是验收通过。
- 本次验证不发送实车运动目标；真实运动/避障/返航效果仍需现场验收。

## 代码证据

- /home/sunrise/luka_ws/src/system/bringup/nx_navigation.launch.py
- /home/sunrise/luka_ws/src/common/config/nx_nav2.yaml
