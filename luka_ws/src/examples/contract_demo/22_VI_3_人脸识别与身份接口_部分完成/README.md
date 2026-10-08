# 22 VI-3 人脸识别与身份接口

合同对应状态：**部分完成**

生产人员服务NX_FACE_ENABLED=0。独立只读演示复用YuNet/SFace，显示参考帧相似度，不修改生产开关，不声称权限联动或迎宾导航已实现。

## 启动及观察

    cd "/home/sunrise/luka_ws/src/examples/contract_demo/22_VI_3_人脸识别与身份接口_部分完成"
    ./demo.sh

启动相机与独立只读YuNet/SFace识别，Foxglove查看/contract_demo/face_image叠加检测框和参考相似度。首个合格人脸作为内存参考，不证明身份认证/权限/迎宾导航。

- ./check.sh：查看launch参数，不启动设备。
- ./demo.sh start_hardware:=false：仅回放/隔离监视，不能作为硬件验收。
- Ctrl+C 或另一个终端 ./stop.sh：停止本launch创建的进程，保留复用的运行服务。
- 按序演示时先结束上一项。完整已有栈可以复用；部分栈/重复串口/SLAM-AMCL冲突会拒绝启动。
- Foxglove连接 ws://192.168.3.150:8765。页面 http://192.168.3.150:8503/。
- 空闲状态、无目标、缺设备时如实显示WAITING；STALE/INVALID不是验收通过。
- 本次验证不发送实车运动目标；真实运动/避障/返航效果仍需现场验收。

## 代码证据

- /home/sunrise/luka_ws/src/perception/luka_face_identity/luka_face_identity/vision.py
- /home/sunrise/luka_ws/src/perception/luka_face_identity/identity.py
- /home/sunrise/luka_ws/src/perception/luka_face_identity/face_reacquire.py
