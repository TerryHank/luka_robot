# 08 II-3 分层ROS节点

合同对应状态：**部分完成**

有底盘/雷达/IMU/SLAM/Nav2；自动回充业务闭环缺失。

## 启动及观察

    cd "/home/sunrise/luka_ws/src/examples/contract_demo/08_II_3_分层ROS节点_部分完成"
    ./demo.sh

真实启动传感器、保护底盘、AMCL、Nav2、相机及现有页面；显示分层节点图和实时消息。自动回充缺失。

- ./check.sh：查看launch参数，不启动设备。
- ./demo.sh start_hardware:=false：仅回放/隔离监视，不能作为硬件验收。
- Ctrl+C 或另一个终端 ./stop.sh：停止本launch创建的进程，保留复用的运行服务。
- 按序演示时先结束上一项。完整已有栈可以复用；部分栈/重复串口/SLAM-AMCL冲突会拒绝启动。
- Foxglove连接 ws://192.168.3.150:8765。页面 http://192.168.3.150:8503/。
- 空闲状态、无目标、缺设备时如实显示WAITING；STALE/INVALID不是验收通过。
- 本次验证不发送实车运动目标；真实运动/避障/返航效果仍需现场验收。

## 代码证据

- /home/sunrise/luka_ws/src/system/bringup/nx_sensors.launch.py
- /home/sunrise/luka_ws/src/system/bringup/nx_navigation.launch.py
