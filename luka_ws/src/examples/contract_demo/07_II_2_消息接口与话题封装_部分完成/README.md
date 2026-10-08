# 07 II-2 消息接口与话题封装

合同对应状态：**部分完成**

有ai_msgs和语义地图自定义消息；底盘控制仍大量使用标准Twist/Odometry，不能宣称有完整专用底盘协议消息。

## 启动及观察

    cd "/home/sunrise/luka_ws/src/examples/contract_demo/07_II_2_消息接口与话题封装_部分完成"
    ./demo.sh

查看真实/wheel/odom、/imu/data、业务消息与实时ROS节点图；保留标准消息/自定义消息覆盖不足的说明。

- ./check.sh：查看launch参数，不启动设备。
- ./demo.sh start_hardware:=false：仅回放/隔离监视，不能作为硬件验收。
- Ctrl+C 或另一个终端 ./stop.sh：停止本launch创建的进程，保留复用的运行服务。
- 按序演示时先结束上一项。完整已有栈可以复用；部分栈/重复串口/SLAM-AMCL冲突会拒绝启动。
- Foxglove连接 ws://192.168.3.150:8765。页面 http://192.168.3.150:8503/。
- 空闲状态、无目标、缺设备时如实显示WAITING；STALE/INVALID不是验收通过。
- 本次验证不发送实车运动目标；真实运动/避障/返航效果仍需现场验收。

## 代码证据

- /home/sunrise/luka_ws/src/common/vendor/ai_msgs/msg/PerceptionTargets.msg
- /home/sunrise/luka_ws/src/map/hotel_semantic_map_msgs/msg/Destination.msg
