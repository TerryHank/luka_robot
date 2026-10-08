# 新工作区合同条款对照说明（差异红字版）

依据：`/home/sunrise/luka_ws` 当前源码、launch、systemd 服务和只读验证入口。

说明：以下按合同原编号逐条对照。正常文字表示在新工作区可以找到对应实现和入口；<span style="color:red">红字表示与合同有出入、只能部分证明，或按用户要求不纳入</span>。红字内容不能解释为已完成交付。

## 一、底层硬件驱动开发

| 合同条款 | 新工作区对应实现 | 对照结论 |
|---|---|---|
| I-1 STM32 底盘固件、串口/RS485/CAN 协议 | `control/ddsm_car_control/ddsm_car_control/zdt_y42_protocol.py`、`zdt_mecanum_rs485_bridge.py`；入口：`start_nx_manual_base.sh` | <span style="color:red">有出入：工作区有 RS485 上位机协议和驱动，但没有 STM32 固件；CAN 不纳入本次范围。</span> |
| I-2 四轮差速运动学、编码器采集、速度闭环 | `zdt_mecanum_kinematics.py`、`zdt_mecanum_rs485_bridge.py`；入口：`start_nx_manual_base.sh` | <span style="color:red">有出入：实际实现是四轮麦克纳姆运动学，不是合同文字中的四轮差速底盘。</span> |
| I-3 六轴 IMU 驱动、姿态解算、滤波融合 | `wit_imu_node.py`、`config/ekf_imu.yaml`、`ekf_imu_yaw_rate.yaml`；入口：`wit_imu.launch.py`、`nx_sensors.launch.py`、`nx_localization.launch.py` | 已实现代码和启动入口；现场精度和标定仍需实车验证。 |
| I-4 激光雷达驱动、点云滤波、畸变矫正、稳定输出 | `low_lidar_udp_proxy.py`、`laser_scan_deskewer.py`、`dual_laser_fusion.py`、`scan_throttler.py`；入口：`nx_sensors.launch.py` | <span style="color:red">有出入：当前链路是二维 `LaserScan`，不是三维点云；可证明二维扫描滤波、去畸变和融合。</span> |
| I-5 深度相机驱动、图像/深度采集预处理、整机通信 | `perception/spatial_memory/orbbec_ros_camera.py`、`src/OrbbecSDK_ROS2/orbbec_camera`；入口：`luka-ws-orbbec-camera.service`、`astra_pro_plus.launch.py`、`luka-ws-vision.service` | 已实现 Astra Pro Plus RGB-D 接入和数据输出。 |

## 二、ROS2 系统开发

| 合同条款 | 新工作区对应实现 | 对照结论 |
|---|---|---|
| II-1 Ubuntu 22.04 + ROS2 环境和工程框架 | `system/environment.bash`、`src/`、`system/services/` | 已有 ROS2 工程和服务框架；Ubuntu 版本需用 `lsb_release -a` 单独核验。 |
| II-2 底盘、传感器、控制指令专用消息和话题 | `src/ai_msgs`、`src/hotel_semantic_map_msgs`、各驱动节点 | 已实现消息包、话题和节点封装。 |
| II-3 分层底盘、雷达、IMU、SLAM、导航、自动回充节点 | `control/ddsm_car_control`、`perception`、`nx_*` 和 `ddsm_*` launch | <span style="color:red">有出入：底盘、雷达、IMU、SLAM、导航有对应节点；自动回充按用户要求不纳入。</span> |

## 三、SLAM 建图功能

| 合同条款 | 新工作区对应实现 | 对照结论 |
|---|---|---|
| III-1 室内二维激光 SLAM 实时建图 | `config/slam_toolbox_mapping.yaml`；入口：`ddsm_slam.launch.py` | 已实现。 |
| III-2 地图保存、离线加载、断电重启复用 | 地图 YAML/PGM、`mapping_bundle.py`、map saver 配置；入口：`ddsm_bringup.launch.py`、`nx_localization.launch.py` | <span style="color:red">有出入：有地图保存和加载入口；断电后自动复用需要现场持续运行验证，当前不能仅凭源码宣称完整完成。</span> |
| III-3 全局重定位、坐标矫正、场景匹配 | `ddsm_auto_localizer.py`、`s100_boot_localize.py`、`nx_relocalization.py`；入口：`ddsm_bringup.launch.py`、Dashboard 定位入口 | <span style="color:red">有出入：存在重定位代码和入口，但不能证明所有室内场景都能自动成功匹配。</span> |

## 四、路径规划与自主导航

| 合同条款 | 新工作区对应实现 | 对照结论 |
|---|---|---|
| IV-1 全局和局部实时路径规划 | Nav2 planner/Smac/MPPI 参数；入口：`nx_navigation.launch.py` | 已实现代码和启动入口。 |
| IV-2 静态障碍、动态行人避障 | global/local costmap、`collision_monitor`、安全速度链；入口：`nx_navigation.launch.py` | <span style="color:red">有出入：静态障碍和安全链有代码；动态行人避障效果仍需现场传感器和代价地图验证。</span> |
| IV-3 多点导航、巡航、点位记忆、一键返航 | `ddsm_patrol_manager.py`、`patrol_route*.yaml`、`waypoint_store.py`、`ddsm_home_manager.py`；入口：`ddsm_bringup.launch.py`、`start_nx_agent.sh` | <span style="color:red">有出入：软件入口存在；自动回充闭环不纳入，不能表述为完整回充业务。</span> |
| IV-4 缓启停、转弯限速、运动平滑 | `velocity_smoother`、`nx_manual_base.py`、底盘速度限幅；入口：`nx_navigation.launch.py`、`start_nx_manual_base.sh` | 已实现软件限速、平滑和超时停车。 |

## 五、基站自动回充功能

| 合同条款 | 新工作区对应实现 | 对照结论 |
|---|---|---|
| V-1 充电桩标定、信号识别、坐标匹配 | 无完整实现 | <span style="color:red">不纳入：硬件缺失或开发方向已改变。</span> |
| V-2 自主返航、精准对位、自动停靠充电 | `ddsm_home_manager.py` 仅有软件返航位姿逻辑 | <span style="color:red">有出入：没有完整充电桩识别、精准对位和自动停靠闭环。</span> |
| V-3 低电量触发、失败重试、绕障回充 | 无完整实现 | <span style="color:red">不纳入：按用户要求忽略。</span> |
| V-4 充电状态、充满脱离、待机 | 无完整实现 | <span style="color:red">不纳入：按用户要求忽略。</span> |

## 六、应用接口规范与功能

| 合同条款 | 新工作区对应实现 | 对照结论 |
|---|---|---|
| VI-1 声源识别、方位检测、导航转向和趋近 | `nx_xfm_doa.py`、`nx_voice_gateway.py`、`nx_voice_commands.py`、`system/nav_llm_agent`；入口：`start_nx_voice.sh`、`start_nx_agent.sh` | <span style="color:red">有出入：有 DOA、语音路由和导航命令代码；完整通信协议及现场趋近闭环仍需单独验收。</span> |
| VI-2 烟雾采集、告警、返航/值守联动 | 无 | <span style="color:red">不纳入：烟雾硬件接口缺失，按用户要求忽略。</span> |
| VI-3 人脸识别、身份认证、权限联动、迎宾导航 | `face_reacquire.py`、`identity.py`、SFace 模型、`worker.py`；入口：`luka-ws-people.service` | <span style="color:red">有出入：人脸代码存在，但当前服务配置关闭人脸；权限联动和迎宾导航没有作为已完成项声明。</span> |
| VI-4 完整《应用接口规范文档》 | `examples/contract_feature_traceability.md`、`examples/contract_clause_traceability_strict.md` | <span style="color:red">有出入：当前文件是功能追溯和验收说明，不等同于合同要求的完整协议规范文档。</span> |

## 七、整机业务与交付服务

| 合同条款 | 新工作区对应实现 | 对照结论 |
|---|---|---|
| VII-1 待机、手动、建图、导航、巡航、回充、故障告警及接口联动状态机 | `ddsm_mission_control.py`、任务状态代码；入口：`ddsm_bringup.launch.py`、`start_nx_manual_base.sh` | <span style="color:red">有出入：待机、手动、导航、巡航、故障等软件状态存在；自动回充状态按用户要求不纳入。</span> |
| VII-2 故障自检、异常上报、运行日志 | `robot_diagnostics.py`、`nx_runtime_health.py`、任务/跟随状态上报；入口：Dashboard、systemd journal、只读 probe | 已实现软件诊断、状态上报和日志链路。 |
| VII-3 源代码、固件、配置、技术文档和接口规范交付 | 工作区源码、配置、`examples/` 文档；版本：GitHub `main` | <span style="color:red">有出入：源码、配置和部分文档已交付；STM32 固件和完整合同交付包按用户要求不纳入。</span> |
| VII-4 线上培训、一年软件质保、持续维护 | 无源码对应 | <span style="color:red">无代码证明：这是服务承诺，不能由工作区源码证明。</span> |

## 只读验证入口

```bash
source /home/sunrise/luka_ws/src/system/environment.bash
bash /home/sunrise/luka_ws/src/examples/contract_readonly_probe.sh
```

该脚本只读取话题、服务和状态，不启用导航、不启用人体跟随、不发布速度指令。

本报告对应的新工作区版本：`52a042b59471b83e0c5a363f659d81648a2974e6`。
