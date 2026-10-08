# 已实现合同功能与启动证明

本文只收录新工作区已经实现的功能。硬件缺失、开发方向已经改变或没有现成闭环的合同条目不列入本表。

状态含义：

- 已实现：有实现代码，并有现成 launch、systemd 服务或可执行验证入口。
- 部分实现：代码和入口存在，但仍需实车/现场条件才能完成最终验收。

## 底盘、传感器和 ROS2

| 已实现功能 | 主要代码 | 启动或证明入口 | 状态 |
|---|---|---|---|
| RS485 电机协议与底盘驱动 | `control/ddsm_car_control/ddsm_car_control/zdt_y42_protocol.py`、`zdt_mecanum_rs485_bridge.py` | `start_nx_manual_base.sh`；`control/ddsm_car_control/launch/zdt_y42_mecanum.launch.py` | 已实现 |
| 四轮麦克纳姆运动学、速度解算、编码器里程计 | `zdt_mecanum_kinematics.py`、`zdt_mecanum_rs485_bridge.py` | 同上 | 已实现 |
| IMU 驱动 | `wit_imu_node.py` | `control/ddsm_car_control/launch/wit_imu.launch.py`、`nx_sensors.launch.py` | 已实现 |
| IMU/EKF 数据融合 | `config/ekf_imu.yaml`、`ekf_imu_yaw_rate.yaml` | `control/ddsm_car_control/launch/ddsm_robot_bringup.launch.py`、`nx_localization.launch.py` | 已实现 |
| 上下两路激光雷达驱动 | `low_lidar_udp_proxy.py`、RPLIDAR 节点配置 | `nx_sensors.launch.py` | 已实现 |
| 雷达滤波、去畸变和双雷达融合 | `laser_scan_deskewer.py`、`dual_laser_fusion.py`、`scan_throttler.py` | `nx_sensors.launch.py` | 已实现 |
| Orbbec Astra Pro Plus RGB-D 接入 | `perception/spatial_memory/orbbec_ros_camera.py`、Orbbec SDK ROS2 源码 | `luka-ws-orbbec-camera.service`；`src/OrbbecSDK_ROS2/orbbec_camera/launch/astra_pro_plus.launch.py` | 已实现 |
| RGB-D 时间匹配和深度预处理 | `orbbec_ros_camera.py`、`people_camera.py` | `luka-ws-vision.service`、`luka-ws-people.service` | 已实现 |
| ROS2 分层工程与专用感知消息 | `src/ai_msgs`、`src/hotel_semantic_map_msgs` | `system/bringup` 和 `system/services` | 已实现 |

## SLAM、地图和定位

| 已实现功能 | 主要代码 | 启动或证明入口 | 状态 |
|---|---|---|---|
| 2D 激光 SLAM 在线建图 | `control/ddsm_car_control/config/slam_toolbox_mapping.yaml` | `control/ddsm_car_control/launch/ddsm_slam.launch.py` | 已实现 |
| SLAM 与 Nav2 联合启动 | `ddsm_slam.launch.py`、`ddsm_nav_slam.launch.py` | `control/ddsm_car_control/launch/ddsm_nav_slam.launch.py` | 已实现 |
| 静态地图加载 | `map/maps/ddsm_map_floor_*.yaml` | `nx_localization.launch.py`、`luka-ws-hardware@localization.service` | 已实现 |
| 地图保存和地图复用 | Nav2 map saver 配置、`visualization/console/mapping_bundle.py` | `ddsm_bringup.launch.py` 及地图工具脚本 | 部分实现 |
| AMCL 定位 | `nav2_mecanum_mppi_params.yaml`、AMCL 配置 | `nx_localization.launch.py` | 已实现 |
| 自动定位、重定位和初始位姿处理 | `ddsm_auto_localizer.py`、`s100_boot_localize.py`、`nx_relocalization.py` | `ddsm_bringup.launch.py`、Dashboard 定位入口 | 部分实现 |

## 导航、避障和巡航

| 已实现功能 | 主要代码 | 启动或证明入口 | 状态 |
|---|---|---|---|
| 全局路径规划 | Nav2 planner/Smac 参数 | `nx_navigation.launch.py` | 已实现 |
| 局部 MPPI 路径跟踪 | `common/config/nx_nav2.yaml` | `nx_navigation.launch.py` | 已实现 |
| 静态和动态障碍物代价地图 | local/global costmap 配置 | `nx_navigation.launch.py` | 已实现 |
| 碰撞监测和速度安全链 | `collision_monitor`、`lateral_escape_guard.py` | `nx_navigation.launch.py` | 已实现 |
| 底盘速度限幅、平滑和超时停车 | `zdt_mecanum_rs485_bridge.py`、`velocity_smoother` | `start_nx_manual_base.sh`、`nx_navigation.launch.py` | 已实现 |
| 定点导航 | Nav2 action、named navigation 相关节点 | `nx_navigation.launch.py`、`ddsm_bringup.launch.py` | 已实现 |
| 多点巡航 | `ddsm_patrol_manager.py`、`patrol_route*.yaml` | `ddsm_bringup.launch.py` | 部分实现 |
| 任务暂停、恢复、取消和手动接管 | `ddsm_mission_control.py`、`nx_manual_base.py` | `ddsm_bringup.launch.py`、`start_nx_manual_base.sh` | 已实现 |
| 返航到已保存 Home/充电点坐标 | `ddsm_home_manager.py`、`home_pose.yaml`、waypoint store | `ddsm_bringup.launch.py`、Agent 启动脚本 | 部分实现 |

## 人体检测、深度和跟随

| 已实现功能 | 主要代码 | 启动或证明入口 | 状态 |
|---|---|---|---|
| YOLO26 Seg BPU 人体检测 | `perception/person_follow/yolo26_bpu_person.py`、`worker.py` | `luka-ws-people.service` | 已实现 |
| 只保留 person 类别 | `yolo26_bpu_person.py` 中 class id 0 过滤 | 同上 | 已实现 |
| Seg Mask 深度估计 | `seg_depth_geometry.py`、`worker.py` | `luka-ws-people.service` | 已实现 |
| 15% trimmed mean 深度 | `seg_depth_geometry.py`、`worker.py` | `luka-ws-people.service` | 已实现 |
| 自动选择单个人体 | `selection.py`、`bridge.py` | `control/luka_person_following/launch/selected_follow.launch.py` | 已实现 |
| 目标有效性、TF、深度和 ID 门控 | `selection.py`、`bridge.py` | `selected_follow.launch.py` | 已实现 |
| 官方人体跟随适配 | `control/luka_person_following/luka_person_following/bridge.py` | `selected_follow.launch.py` | 部分实现；现场运行前需保证只启动一个官方跟随实例并确认速度话题接线 |
| 人体跟随安全速度限制 | `nx_manual_base.py`、`web_teleop_safety.py` | `start_nx_manual_base.sh` | 已实现 |

## 语音和业务接口中已存在的部分

| 已实现功能 | 主要代码 | 启动或证明入口 | 状态 |
|---|---|---|---|
| 语音识别、唤醒和语音命令路由 | `visualization/console/nx_voice_gateway.py`、`nx_voice_commands.py`、语音模型目录 | `system/bringup/start_nx_voice.sh`、`ddsm_bringup.launch.py` | 部分实现 |
| 声源 DOA 数据接入 | `visualization/console/nx_xfm_doa.py`、`common/runtime/xfm_doa.json` | `start_nx_voice.sh` 相关入口 | 部分实现 |
| 语音导航/返航命令 | `system/nav_llm_agent`、`waypoint_store.py`、Agent capability registry | `system/bringup/start_nx_agent.sh`、`ddsm_bringup.launch.py` | 部分实现 |
| 人脸识别和目标重识别代码 | `face_reacquire.py`、`identity.py`、`worker.py`、SFace 模型 | `luka-ws-people.service` | 部分实现；当前服务配置关闭人脸识别 |

## 整机状态和诊断

| 已实现功能 | 主要代码 | 启动或证明入口 | 状态 |
|---|---|---|---|
| 待机、手动、导航、巡航、暂停、恢复状态机 | `ddsm_mission_control.py` | `ddsm_bringup.launch.py` | 已实现 |
| IMU、编码器、雷达和 TF 健康门控 | `nx_manual_base.py`、`bridge.py`、`ddsm_mission_control.py` | systemd 启动的硬件栈 | 已实现 |
| 任务安全状态和跟随适配状态上报 | `/hotel/mission/safety_status`、`/luka_person_following/adapter_status` | 对应节点启动入口 | 已实现 |
| 运行日志和诊断工具 | `robot_diagnostics.py`、`nx_runtime_health.py`、systemd journal | Dashboard/systemd | 已实现 |

## 可直接执行的无移动证明命令

```bash
source /home/sunrise/luka_ws/src/system/environment.bash

ros2 topic echo /scan --once
ros2 topic echo /scan_low_filtered --once
ros2 topic echo /imu/data --once
ros2 topic echo /amcl_pose --once
ros2 topic echo /luka_person_following/adapter_status --once
ros2 topic info /nx/nav_safe -v
ros2 service list | grep -E 'navigation_enable|set_enabled|pause_now|resume_now'
```

这些命令只检查话题、服务和状态，不发送运动命令。
