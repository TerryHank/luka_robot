# 接口清单

QoS 的 R/V 表示 reliable/volatile；R/T 表示 reliable/transient_local；BE/V 表示 best_effort/volatile。
设备端原始读回记录在 log/person_follow_live/evidence.json；下表区分实际数据和待验证导航接口。

| 接口 | 类型 | Frame / 数据 | 发布者 → 订阅者 | QoS / 验证 |
|---|---|---|---|---|
| /camera/color/image_raw | sensor_msgs/msg/Image | camera_color_optical_frame，640×480 rgb8 | 原 Astra → 格式适配器 | R/V depth10，实采 |
| /camera/depth/image_raw | sensor_msgs/msg/Image | 同 color optical frame，640×480 16UC1 | 原 Astra → 配对器 | R/V depth10，实采；物理距离待人工测量 |
| /camera/color/camera_info | sensor_msgs/msg/CameraInfo | 配准 color 内参 | 原 Astra → 融合 | R/V depth10，实采 |
| /person_follow/image_nv12 | sensor_msgs/msg/Image | 原尺寸、原 header，step=width | 格式适配器 → 官方 DNN | R/V depth2，实采及像素/头部测试 |
| /hobot_dnn_seg | ai_msgs/msg/PerceptionTargets | 原 color header，真实 160×120 标签掩码 | 官方 DNN → 配对器 | R/V depth10，实采 |
| /hobot_dnn_seg_info | ai_msgs/msg/PerceptionInfo | 对应图像尺寸/类别 | 官方 DNN → 融合 | R/V depth10，官方接口 |
| /person_follow/fusion/depth | sensor_msgs/msg/Image | 配准图像不变，stamp 配为 seg stamp | 配对器 → 融合 ExactTime | R/V depth10，实采及异常测试 |
| /person_follow/fusion/seg | ai_msgs/msg/PerceptionTargets | 原分割数据与 stamp | 配对器 → 融合 ExactTime | R/V depth10，实采 |
| /person_follow/pair_skew_sec | std_msgs/msg/Float64 | 原 depth stamp - seg stamp | 配对器 → 诊断 | R/V depth10，最大实测绝对差约12.59ms |
| /tros_fusion_interaction | ai_msgs/msg/PerceptionTargets | 原 optical header；空间属性按 camera_link 解释 | 官方融合 → 官方 MOT | R/V depth10，空场景实采和合成空间测试 |
| /tros_mot_targets | ai_msgs/msg/PerceptionTargets | 原 header/attributes 保留，分配 track_id | 官方 MOT → 跟随核心 | R/V depth10；核心订阅 BE/V depth1 |
| /person_follow/fusion/debug_map | nav_msgs/msg/OccupancyGrid | camera_link，融合内部调试栅格 | 官方融合 → 调试 | 官方 R/V depth10；不接入 Nav2 |
| /global_costmap/costmap | nav_msgs/msg/OccupancyGrid | map，0..100，-1 未知 | 原 Nav2 → 核心 | 核心请求 R/T depth1；实际 server 未就绪 |
| /navigate_to_pose | nav2_msgs/action/NavigateToPose | map，有限位置和单位四元数 | 核心 → 原 Nav2 | 实际 server 未就绪；模拟 Action 已验 |
| /person_follow/enable_follow | std_srvs/srv/SetBool | 本模块启停，默认关闭 | 操作员 → 核心 | 标准服务 |
| /person_follow/goal_candidate | geometry_msgs/msg/PoseStamped | map，有效时间戳 | 核心 dry_run → 调试 | R/V depth10；模拟已验 |
| /person_follow/nearest_pose | geometry_msgs/msg/PoseStamped | map，可视化，不等同 Action 决策 | 核心 → 调试 | R/V depth1 |
| /person_follow/tros_tracking_status | std_msgs/msg/String | 官方状态、id、dist | 核心 → UI | R/T depth10 |
| /person_follow/integration_diagnostics | std_msgs/msg/String | 模式、门控、发送/接受/结果 | 核心 → UI | R/T depth10 |

## 关键数据约定

官方分割 `parking_space` target 的 captures.features 保存真实标签数组，captures.img 提供 160×120 尺寸；person 的 2D ROI 是另一个 target。
实际标签 chair=57、refrigerator=73，符合 COCO 类别+背景偏移；合成 person 标签1已通过融合测试。
格式适配不制造掩码，配对器拒绝仅有人体框、无掩码、NaN 掩码、深度长度错误、错误 Frame、过期数据及超限配对。

融合输出虽然保留 camera_color_optical_frame header，但 x_cm/y_cm 空间属性经 point_cloud_target_frame=camera_link 处理。
合成深度验证 x_cm 为前向厘米，左侧 y_cm 为正，右侧为负，width_cm/height_cm 为有效正值。
核心使用配置化 camera_frame=camera_link 解释这些空间字段，不能直接用 optical header 当成 X 前向参考。
map→base→camera 的现场安装外参仍需验证，不增加虚假单位 TF。

新核心感知超时0.6s、动态 TF 超时0.6s、Costmap 超时2.0s；无效/未知/占用栅格不发目标。
旋转栅格、非 map 栅格、数据长度错误等拒绝。地图栅格消耗正确的 OccupancyGrid 0..100 语义，不误当 raw Costmap2D 字节。
