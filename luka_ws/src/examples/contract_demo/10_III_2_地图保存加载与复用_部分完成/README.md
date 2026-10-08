# 10 III-2 地图保存加载与复用

合同对应状态：**部分完成**

提供静态地图加载入口和独立save_map.sh；保存调用已有mapping_bundle且要求SLAM活跃。断电自动复用未实测。

## 启动及观察

    cd "/home/sunrise/luka_ws/src/examples/contract_demo/10_III_2_地图保存加载与复用_部分完成"
    ./demo.sh

加载现有楼层地图，实时显示地图尺寸/分辨率。建图保存另用本目录save_map.sh：先停止本加载入口并运行09建图，再保存，不同时运行SLAM与AMCL。

- ./check.sh：查看launch参数，不启动设备。
- ./demo.sh start_hardware:=false：仅回放/隔离监视，不能作为硬件验收。
- Ctrl+C 或另一个终端 ./stop.sh：停止本launch创建的进程，保留复用的运行服务。
- 按序演示时先结束上一项。完整已有栈可以复用；部分栈/重复串口/SLAM-AMCL冲突会拒绝启动。
- Foxglove连接 ws://192.168.3.150:8765。页面 http://192.168.3.150:8503/。
- 空闲状态、无目标、缺设备时如实显示WAITING；STALE/INVALID不是验收通过。
- 本次验证不发送实车运动目标；真实运动/避障/返航效果仍需现场验收。

## 代码证据

- /home/sunrise/luka_ws/src/visualization/console/mapping_bundle.py
- /home/sunrise/luka_ws/src/visualization/console/s100_boot_pose.py
- /home/sunrise/luka_ws/src/system/bringup/nx_localization.launch.py
