# RDK S100 官方人体跟随：工程审计

日期：2026-10-08。目标：`sunrise@192.168.3.150:/home/sunrise/luka_ws`。
本轮曾使用同机 `10.0.0.106`，最终按用户指示恢复使用 `192.168.3.150`。

## 工作区和原有修改

- 所有源码保持 `luka_ws/src/<领域>/<包>`，构建产物在 build/install/log，未增加根目录快捷方式。
- 当前 `colcon list --base-paths src` 发现 **20 个唯一包**。跟随核心只有 `src/control/tros_person_following` 一份参与构建。
- 迁移前 HEAD：`5ab81a3c00083350372d21842d38a677a2436ef7`。
- 上游完整 Git 克隆位于 `/home/sunrise/luka_upstream/tros_person_following`，父目录具有 COLCON_IGNORE，位于工作区之外。
- 原有未提交修改先备份：`/home/sunrise/luka_migration_backups/person-following-integration-20261008-124659`，含原文件、SHA256、二进制 Git diff 和原 HEAD。
- 原有 bridge/selection/selected_follow.launch/setup/target_relock 文件经逐字节比较均未改变。
- 核心原有 `navigate_to_pose_action_name`、`single_person_auto_relock` 扩展保留；新入口显式关闭后者，不把旧 HTTP 选人链路作为本轮数据源。

## 版本与依赖

| 项目 | 核实结果 |
|---|---|
| 系统 | Ubuntu 22.04.5 LTS，arm64，RDK S100 |
| ROS | Humble，`/opt/ros/humble`；本机没有 `/opt/tros` |
| S100 DNN / 固件 | hobot-dnn 4.0.5-20260211103825 / hobot-firmware 4.0.5-20260507202525 |
| Follow 上游 | develop 固定 `202e8c8a04dc41e3d3771daa131b852cc24f7c0d`，完整 6 提交历史，git fsck 通过 |
| MOT 上游参考 | `0120205146d88c3474bfc2936522e349e169fa8d` |
| DNN 源码参考 | `a5d6c3312315599b03d09ce5f00a8a9761702f12` |
| StereoNet 参考 | `46347588bbc172080ca95d16c4f798c00529f62b`，未启用；现场不是 RGB 双目相机 |
| 官方融合 | VIMS 0.0.6 发布包，hobot_obstacle_depth_fusion 0.0.1，独立提取二进制及 runtime-stats |
| S100 dnn_node / example | 2.6.1-jammy.20260506.085853 / 2.6.1-jammy.20260506.100419，下载解包，未执行系统安装/升级 |
| 分割模型 | 已有 `/opt/hobot/model/s100/basic/yolov8n_seg_640x640_nv12.hbm`，4055736 字节 |

官方 VIMS 整包 SHA256 与发布校验文件一致：
`f2b2ccc554d77de7ec9b2df1e7f336068175acd7442bb859ba2b6e519d294d34`。
依赖具体校验值见 `dependencies.lock.json`。没有安装整套 X5 VIMS、替换 Nav2/SLAM 或修改系统配置。

## 现场数据与限制

实际相机是 Astra Pro Plus RGB-D，已有启动配置为 640×480、depth_registration=true、align_mode=SW。
实际采集验证：RGB 为 rgb8，配准深度为 16UC1，二者均 640×480，header.frame_id 为 camera_color_optical_frame。
color camera_info 的 fx/fy=541.964599609375，cx=320.5293273925781，cy=243.3502197265625。
相机、DNN、融合、MOT 的实际发布者及 QoS 已读回，见接口报告和设备 log/person_follow_live/evidence.json。

初始相机/跟随/导航进程均未运行，Foxglove 和音频服务存在。CLI daemon 曾返回过期节点，后续用新建 rclpy 节点查询。
map→base_link、map→camera_link、全局 Costmap、真实 NavigateToPose server 当前未就绪。
本轮仅启动并清理自己创建的相机与感知进程；没有启动、重建或部署原导航/定位/底盘服务。

当前原生 RGB DNN 路径将 640×480 拉伸为 640×640，因此增加 RGB→NV12 格式转换，使用官方保宽高比路径；实际掩码恢复为 160×120。
官方融合采用 ExactTime，而现场 RGB/深度时间戳不同，因此增加 ≤40ms 的配对器，保留原时间差诊断；不假称硬件严格同步。
VIMS 二进制 enable_pub_map=false 会在 depth_to_point_cloud 崩溃，已用 gdb 定位并复现。采用 enable_pub_map=true，输出到独立调试话题，不接入现有地图/Costmap。

用户明确选择本轮无人、只完成模拟和静态验收。真人尺寸/距离、遮挡以及实际相机安装外参和实车跟随仍待验证。
