# S100 官方人体跟随策略适配

上游：D-Robotics/tros_person_following develop，固定提交 `202e8c8a04dc41e3d3771daa131b852cc24f7c0d`。策略参数契约见 `config/UPSTREAM.json`。

保留当前 Orbbec 注册 RGB-D、定位/SLAM、Nav2、航向约束、碰撞监测和底盘许可链。
主感知链：NV12 格式转换 → S100 YOLOv8n-Seg → 时间配对 → 官方深度融合 → 官方 IOU 2.0/Kalman MOT。

## 策略与运动执行

- 官方 IDLE 观察/旋转找人、TRACKING 距离带/边缘转向、LOST 首观测点/扫描/轮次推进已接回。
- 移动目标继续更新 NavigateToPose；官方 withhold 区间不发送新目标、不取消已有目标；过近时取消自有目标。
- 旋转通过现有 Nav2 `/spin` Action，不直接发布 Twist；速度继续走 `/nx/nav_raw → /nx/nav_smoothed → /nx/nav_guarded → /nx/nav_safe`。
- NavigateToPose 与 Spin 切换等待自有任务终止；旋转前及旋转退出后的导航放行还检查 `/wheel/odom`。
- 停稳门要求有效新鲜里程计、至少两份不同时间戳样本及至少 0.1 s 持续低速，平面速度小于 0.02 m/s、角速度小于 0.05 rad/s。
- Spin 的碰撞检查、角速度和加速度由既有 Nav2 behavior server 控制，官方 `explore_spin_angular_speed` 保留兼容参数但不覆盖本机 Nav2 的速度配置。
- 目标和旋转均按自有句柄/UUID/generation 管理；迟到接受、停止、SIGINT/SIGTERM及输入过期取消自己的任务。
- 扫描仅在成功 Spin 结果后推进；拒绝或失败不伪造扫描完成。官方远距/过渡点跳过扫描的策略仍保留。

上游当前 `pickLkpObservationPose()` 优先返回 LKP，下一轮可能重复同一观测位置；没有把历史文档的“必然选择不同位置”当作当前源码保证。

## 参数与接口

- 显式对齐官方 launch 策略值，包含重锁距离 1/2/3 m、IDLE 搜索延迟 3 s/总时限 60 s、跟随距离 1.8–2.0 m、搜索总时限 8 s及最多2轮。
- 官方单人 MOT 变号桥接行为启用；它不提供持久身份保证，人脸匹配不授权指定身份跟随。
- 蜂鸣策略默认3 s节流；是否实际有声音取决于平台蜂鸣订阅器，未在本轮验证。
- 盲区使能统一发布到 `/enable_blind_zone_observing`；当前导航栈的消费者联动未进行现场验收。
- `config/person_following_s100.yaml` 保留本机 `base_link/camera_link`、图像 640×480 和相机话题。
- 默认 `dry_run`、`follow_enabled_on_start=false`；观测输出为 `/person_follow/goal_candidate`、`/person_follow/spin_candidate`。

## 启动与验收

`src/system/scripts/start_official_person_following.sh` 是唯一整套入口，复用现有相机/TF/Nav2。
不因启动服务自动启用跟随；使用 `/person_follow/enable_follow` SetBool 服务操作。
切换 `nav2_action` 仍要求明确设置 `input_contract_verified=true`，不能把模拟回归等同于现场输入验收。

本轮不启动实车运动。注册测试使用隔离 ROS domain、合成 TF/深度/MOT、模拟 NavigateToPose/Spin 服务器；不发布电机速度。
真人遮挡/交叉、实际旋转速度、8秒搜索预算内的可完成轮次、近障转向和实测最终停稳均待现场验收。
