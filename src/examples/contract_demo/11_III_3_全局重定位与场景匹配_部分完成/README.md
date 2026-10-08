# 11 III-3 全局重定位与场景匹配

合同对应状态：**部分完成**

有AMCL/全局重定位/扫描匹配；本入口不自动调用可能旋转底盘的重定位请求。场景适应效果未验收。

## 启动及观察

    cd "/home/sunrise/luka_ws/src/examples/contract_demo/11_III_3_全局重定位与场景匹配_部分完成"
    ./demo.sh

启动AMCL与现有定位页面，显示/amcl_pose坐标。初始位姿由Foxglove或现有页面设置；不自动触发旋转重定位。

- ./check.sh：查看launch参数，不启动设备。
- ./demo.sh start_hardware:=false：仅回放/隔离监视，不能作为硬件验收。
- Ctrl+C 或另一个终端 ./stop.sh：停止本launch创建的进程，保留复用的运行服务。
- 按序演示时先结束上一项。完整已有栈可以复用；部分栈/重复串口/SLAM-AMCL冲突会拒绝启动。
- Foxglove连接 ws://192.168.3.150:8765。页面 http://192.168.3.150:8503/。
- 空闲状态、无目标、缺设备时如实显示WAITING；STALE/INVALID不是验收通过。
- 本次验证不发送实车运动目标；真实运动/避障/返航效果仍需现场验收。

## 代码证据

- /home/sunrise/luka_ws/src/visualization/console/nx_relocalization.py
- /home/sunrise/luka_ws/src/visualization/console/nx_scan_map_match.py
- /home/sunrise/luka_ws/src/control/ddsm_car_control/ddsm_car_control/ddsm_auto_localizer.py
