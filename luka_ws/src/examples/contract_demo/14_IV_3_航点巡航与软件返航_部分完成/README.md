# 14 IV-3 航点巡航与软件返航

合同对应状态：**部分完成**

航点/巡航/Home节点存在；无充电停靠闭环，入口只启动节点且不自动发航点/返航/巡航请求。

## 启动及观察

    cd "/home/sunrise/luka_ws/src/examples/contract_demo/14_IV_3_航点巡航与软件返航_部分完成"
    ./demo.sh

启动Home/巡航/任务节点与现有页面，打印路线点数和巡航/Home/任务状态。通过页面明确开始/暂停/停止；不在启动时自动执行任务。

- ./check.sh：查看launch参数，不启动设备。
- ./demo.sh start_hardware:=false：仅回放/隔离监视，不能作为硬件验收。
- Ctrl+C 或另一个终端 ./stop.sh：停止本launch创建的进程，保留复用的运行服务。
- 按序演示时先结束上一项。完整已有栈可以复用；部分栈/重复串口/SLAM-AMCL冲突会拒绝启动。
- Foxglove连接 ws://192.168.3.150:8765。页面 http://192.168.3.150:8503/。
- 空闲状态、无目标、缺设备时如实显示WAITING；STALE/INVALID不是验收通过。
- 本次验证不发送实车运动目标；真实运动/避障/返航效果仍需现场验收。

## 代码证据

- /home/sunrise/luka_ws/src/control/ddsm_car_control/ddsm_car_control/ddsm_patrol_manager.py
- /home/sunrise/luka_ws/src/control/ddsm_car_control/ddsm_car_control/ddsm_home_manager.py
- /home/sunrise/luka_ws/src/system/nav_llm_agent/nav_llm_agent/waypoint_store.py
