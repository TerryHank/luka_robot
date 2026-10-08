# 合同条款逐条对应矩阵

本文按合同原编号逐条列出，不把多个合同条款合并成一个“功能组”。每行只能对应一个合同条款；每个条款必须同时给出代码证据、启动/验证入口和状态。

状态定义：

- **已实现**：工作区有对应实现，且有 launch、systemd 或只读验证入口。
- **部分实现**：有部分代码或启动入口，但合同描述的完整闭环仍缺少证据。
- **不纳入**：按用户要求，硬件缺失或开发方向已改变，不作为新工作区交付范围。
- **无代码证明**：合同要求属于文档、培训、质保等交付行为，不能用源码证明。

## 逐条矩阵

| 合同编号 | 合同条款 | 对应代码 | 启动/证明入口 | 状态 | 不能扩大解释的地方 |
|---|---|---|---|---|---|
| I-1 | STM32 固件、串口/RS485/CAN 协议 | `control/ddsm_car_control/ddsm_car_control/zdt_y42_protocol.py`、`zdt_mecanum_rs485_bridge.py` | `start_nx_manual_base.sh` | 不纳入 | 工作区有 RS485 上位机协议，但没有 STM32 固件和 CAN 交付物。 |
| I-2 | 四轮差速运动学、编码器采集、速度闭环 | `zdt_mecanum_kinematics.py`、`zdt_mecanum_rs485_bridge.py` | `start_nx_manual_base.sh` | 部分实现 | 实际实现是四轮麦克纳姆，不是合同字面上的四轮差速；不能标为完全对应。 |
| I-3 | 六轴 IMU 驱动、姿态解算、滤波融合 | `wit_imu_node.py`、`config/ekf_imu.yaml`、`ekf_imu_yaw_rate.yaml` | `wit_imu.launch.py`、`nx_sensors.launch.py`、`nx_localization.launch.py` | 已实现 | 现场传感器精度和标定效果仍需实车验收。 |
| I-4 | 激光雷达驱动、点云滤波、畸变矫正、稳定输出 | `low_lidar_udp_proxy.py`、`laser_scan_deskewer.py`、`dual_laser_fusion.py`、`scan_throttler.py` | `nx_sensors.launch.py` | 部分实现 | 当前数据链路是 `LaserScan`，不是 3D 点云；只能证明二维扫描滤波、去畸变和融合。 |
| I-5 | 深度相机驱动、图像/深度采集预处理及整机通信 | `perception/spatial_memory/orbbec_ros_camera.py`、`src/OrbbecSDK_ROS2/orbbec_camera` | `luka-ws-orbbec-camera.service`、`astra_pro_plus.launch.py`、`luka-ws-vision.service` | 已实现 | 证明的是 Astra Pro Plus RGB-D 链路。 |
| II-1 | Ubuntu 22.04 + ROS2 环境和工程框架 | `system/environment.bash`、`src/`、`system/services/` | systemd 服务和 `source /home/sunrise/luka_ws/src/system/environment.bash` | 已实现 | OS 版本属于部署环境，应以 `lsb_release -a` 单独核验。 |
| II-2 | 底盘、传感器、控制指令专用消息和话题封装 | `src/ai_msgs`、`src/hotel_semantic_map_msgs`、各驱动节点 | `system/bringup`、`system/services`、只读 probe | 已实现 | 只证明仓库中已有消息和话题，不证明合同之外的新协议。 |
| II-3 | 分层底盘、雷达、IMU、SLAM、导航、回充节点 | `control/ddsm_car_control`、`perception`、`nx_*` launch、`ddsm_*` launch | `nx_sensors.launch.py`、`nx_localization.launch.py`、`nx_navigation.launch.py`、`ddsm_bringup.launch.py` | 部分实现 | 回充层按用户要求不纳入，因此本条不能标为完整实现。 |
| III-1 | 室内二维激光 SLAM 实时建图 | `config/slam_toolbox_mapping.yaml` | `ddsm_slam.launch.py` | 已实现 | 算法参数仍需现场调优。 |
| III-2 | 地图保存、离线加载、断电重启复用 | 地图 YAML/PGM、`mapping_bundle.py`、map saver 配置 | `ddsm_bringup.launch.py`、`nx_localization.launch.py`、地图工具脚本 | 部分实现 | 有保存和加载入口；“断电后自动复用”的持续运行证据需现场验证。 |
| III-3 | 全局重定位、坐标矫正、自适应匹配 | `ddsm_auto_localizer.py`、`s100_boot_localize.py`、`nx_relocalization.py` | `ddsm_bringup.launch.py`、Dashboard 定位入口 | 部分实现 | 有重定位代码和入口，不能据此承诺所有场景自动成功。 |
| IV-1 | 全局和局部实时路径规划 | Nav2 planner/Smac/MPPI 参数、导航节点 | `nx_navigation.launch.py` | 已实现 | 规划器配置存在，现场地图质量仍影响结果。 |
| IV-2 | 静态障碍和动态行人避障 | global/local costmap、`collision_monitor`、安全链 | `nx_navigation.launch.py` | 部分实现 | 静态障碍和安全链有代码；动态行人避障需以现场传感器和代价地图实测为准。 |
| IV-3 | 多点导航、巡航、点位记忆、一键返航 | `ddsm_patrol_manager.py`、`patrol_route*.yaml`、`waypoint_store.py`、`ddsm_home_manager.py` | `ddsm_bringup.launch.py`、`start_nx_agent.sh` | 部分实现 | 软件入口存在；完整自动回充闭环按用户要求不纳入。 |
| IV-4 | 缓启停、转弯限速、运动平滑 | `velocity_smoother`、`nx_manual_base.py`、底盘速度限幅 | `nx_navigation.launch.py`、`start_nx_manual_base.sh` | 已实现 | 只证明软件限速和平滑控制。 |
| V-1 | 充电桩标定、信号识别、坐标匹配 | 无可交付的完整实现 | 无 | 不纳入 | 硬件和开发方向已改变。 |
| V-2 | 返航、精准对位、自动停靠充电 | `ddsm_home_manager.py` 仅包含软件返航位姿 | `ddsm_bringup.launch.py` | 不纳入 | 只有返航软件逻辑，没有完整充电硬件闭环。 |
| V-3 | 低电量触发、失败重试、绕障回充 | 无完整实现 | 无 | 不纳入 | 按用户要求忽略。 |
| V-4 | 充电状态、充满脱离、待机 | 无完整实现 | 无 | 不纳入 | 按用户要求忽略。 |
| VI-1 | 声源识别、方位检测、导航转向和趋近接口 | `nx_xfm_doa.py`、`nx_voice_gateway.py`、`nx_voice_commands.py`、`system/nav_llm_agent` | `start_nx_voice.sh`、`start_nx_agent.sh` | 部分实现 | 有 DOA/语音路由代码，完整通信协议和现场趋近闭环需另行验收。 |
| VI-2 | 烟雾接口、告警、返航/值守联动 | 无 | 无 | 不纳入 | 硬件接口缺失，按用户要求忽略。 |
| VI-3 | 人脸识别、身份认证、权限联动、迎宾导航 | `face_reacquire.py`、`identity.py`、SFace 模型、`worker.py` | `luka-ws-people.service` | 部分实现 | 人脸代码存在，但当前服务配置关闭人脸；权限和迎宾闭环没有作为已完成项声明。 |
| VI-4 | 完整《应用接口规范文档》 | `examples/contract_feature_traceability.md`、本矩阵 | `examples/contract_readonly_probe.sh` | 无代码证明 | 当前文件是追溯和验收说明，不等同于合同要求的完整协议规范文档。 |
| VII-1 | 待机、手动、建图、导航、巡航、回充、故障和接口联动状态机 | `ddsm_mission_control.py`、任务状态代码 | `ddsm_bringup.launch.py`、`start_nx_manual_base.sh` | 部分实现 | 非回充状态有实现；自动回充状态按用户要求不纳入。 |
| VII-2 | 故障自检、异常上报、运行日志 | `robot_diagnostics.py`、`nx_runtime_health.py`、任务/跟随状态上报 | Dashboard、systemd journal、只读 probe | 已实现 | 证明的是已有软件诊断和日志链路。 |
| VII-3 | 完整源代码、固件、配置和技术文档交付 | 工作区源码、配置、`examples/` 文档 | GitHub `main`、工作区目录 | 部分实现 | 源码/配置/部分文档已在工作区；STM32 固件和完整合同交付包按用户要求不纳入。 |
| VII-4 | 培训、一年质保、持续适配维护 | 无源码可证明 | 无 | 无代码证明 | 这是服务承诺，不应伪装成代码功能。 |

## 如何检查是否真的一一对应

1. 合同编号必须全部出现一次；不能用“人体跟随”“导航能力”等模糊大类替代编号。
2. 每行只能有一个合同编号；多个源码文件可以作为同一条款的证据，但不能把一条源码证据反向当成多个合同承诺。
3. 每行必须同时具备“代码路径”和“启动/验证入口”；缺一项就只能标为部分实现或无代码证明。
4. 对“差速/点云/完整回充”等合同原词做字面核对，实际是麦克纳姆、二维 LaserScan 或软件返航时，必须在差异列明示。
5. 运行证明只使用只读命令；`examples/contract_readonly_probe.sh` 不启用导航、不启用跟随、不发布速度。
6. Git 提交记录和远端 HEAD 作为交付版本证据；当前工作区对应提交为 `322881b2a75ccb3a922a94479fef3613dd4a1790`。
