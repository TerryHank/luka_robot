# 25 VII-2 故障自检与运行日志

合同对应状态：**代码已完成_待现场验收**

软件健康检查、故障快照与日志链存在；传感器断联会如实显示未就绪。

## 启动及观察

    cd "/home/sunrise/luka_ws/src/examples/contract_demo/25_VII_2_故障自检与运行日志_代码已完成_待现场验收"
    ./demo.sh

启动现有诊断页面，显示真实ROS节点图及安全状态。页面查看健康检查/故障快照/日志；本入口不伪造设备故障或全部健康。

- ./check.sh：查看launch参数，不启动设备。
- ./demo.sh start_hardware:=false：仅回放/隔离监视，不能作为硬件验收。
- Ctrl+C 或另一个终端 ./stop.sh：停止本launch创建的进程，保留复用的运行服务。
- 按序演示时先结束上一项。完整已有栈可以复用；部分栈/重复串口/SLAM-AMCL冲突会拒绝启动。
- Foxglove连接 ws://192.168.3.150:8765。页面 http://192.168.3.150:8503/。
- 空闲状态、无目标、缺设备时如实显示WAITING；STALE/INVALID不是验收通过。
- 本次验证不发送实车运动目标；真实运动/避障/返航效果仍需现场验收。

## 代码证据

- /home/sunrise/luka_ws/src/visualization/console/robot_diagnostics.py
- /home/sunrise/luka_ws/src/visualization/console/nx_runtime_health.py
