# 05 I-5 RGBD深度相机

合同对应状态：**代码已完成_待现场验收**

Astra Pro Plus驱动和RGB-D预处理存在；实时帧率和深度质量需要现场验证。

## 启动及观察

    cd "/home/sunrise/luka_ws/src/examples/contract_demo/05_I_5_RGBD深度相机_代码已完成_待现场验收"
    ./demo.sh

实时打印RGB/深度图像分辨率、编码、时间戳和中心像素深度（米）。Foxglove查看RGB/深度图；INVALID不是有效距离。

- ./check.sh：查看launch参数，不启动设备。
- ./demo.sh start_hardware:=false：仅回放/隔离监视，不能作为硬件验收。
- Ctrl+C 或另一个终端 ./stop.sh：停止本launch创建的进程，保留复用的运行服务。
- 按序演示时先结束上一项。完整已有栈可以复用；部分栈/重复串口/SLAM-AMCL冲突会拒绝启动。
- Foxglove连接 ws://192.168.3.150:8765。页面 http://192.168.3.150:8503/。
- 空闲状态、无目标、缺设备时如实显示WAITING；STALE/INVALID不是验收通过。
- 本次验证不发送实车运动目标；真实运动/避障/返航效果仍需现场验收。

## 代码证据

- /home/sunrise/luka_ws/src/sensing/OrbbecSDK_ROS2/orbbec_camera/launch/astra_pro_plus.launch.py
- /home/sunrise/luka_ws/src/perception/luka_visual_runtime/orbbec_ros_camera.py
