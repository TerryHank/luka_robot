# 09 III-1 二维激光SLAM

合同对应状态：**代码已完成_待现场验收**

只启动现有slam_toolbox算法节点，复用当前传感器和只读里程计；不调用旧ESP32通用整机launch。现场调优未验收。

## 启动及观察

    cd "/home/sunrise/luka_ws/src/examples/contract_demo/09_III_1_二维激光SLAM_代码已完成_待现场验收"
    ./demo.sh

启动slam_toolbox、传感器和只读编码器里程计，实时显示地图尺寸/分辨率/已知栅格。需要键盘移动时先启动01_02，再启动本项复用其底盘和传感器。

- ./check.sh：查看launch参数，不启动设备。
- ./demo.sh start_hardware:=false：仅回放/隔离监视，不能作为硬件验收。
- Ctrl+C 或另一个终端 ./stop.sh：停止本launch创建的进程，保留复用的运行服务。
- 按序演示时先结束上一项。完整已有栈可以复用；部分栈/重复串口/SLAM-AMCL冲突会拒绝启动。
- Foxglove连接 ws://192.168.3.150:8765。页面 http://192.168.3.150:8503/。
- 空闲状态、无目标、缺设备时如实显示WAITING；STALE/INVALID不是验收通过。
- 本次验证不发送实车运动目标；真实运动/避障/返航效果仍需现场验收。

## 代码证据

- /home/sunrise/luka_ws/src/control/ddsm_car_control/config/slam_toolbox_mapping.yaml
