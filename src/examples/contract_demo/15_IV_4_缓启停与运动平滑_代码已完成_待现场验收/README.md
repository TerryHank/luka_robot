# 15 IV-4 缓启停与运动平滑

合同对应状态：**代码已完成_待现场验收**

复用Nav2 velocity_smoother和限幅函数；不直接注入速度，物理平稳性仍需运动验收。

## 启动及观察

    cd "/home/sunrise/luka_ws/src/examples/contract_demo/15_IV_4_缓启停与运动平滑_代码已完成_待现场验收"
    ./demo.sh

启动现有Nav2速度链和保护底盘，打印raw→smoothed→guarded→safe实际速度；未运行导航时WAITING是正常现象，不直接注入速度。

- ./check.sh：查看launch参数，不启动设备。
- ./demo.sh start_hardware:=false：仅回放/隔离监视，不能作为硬件验收。
- Ctrl+C 或另一个终端 ./stop.sh：停止本launch创建的进程，保留复用的运行服务。
- 按序演示时先结束上一项。完整已有栈可以复用；部分栈/重复串口/SLAM-AMCL冲突会拒绝启动。
- Foxglove连接 ws://192.168.3.150:8765。页面 http://192.168.3.150:8503/。
- 空闲状态、无目标、缺设备时如实显示WAITING；STALE/INVALID不是验收通过。
- 本次验证不发送实车运动目标；真实运动/避障/返航效果仍需现场验收。

## 代码证据

- /home/sunrise/luka_ws/src/control/ddsm_car_control/ddsm_car_control/zdt_mecanum_kinematics.py
- /home/sunrise/luka_ws/src/system/bringup/nx_navigation.launch.py
