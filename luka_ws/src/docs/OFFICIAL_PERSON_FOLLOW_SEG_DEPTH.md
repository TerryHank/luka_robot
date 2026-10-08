# 官方人体跟随与分割平均深度接入

最新性能修复：已将人物筛选提前到掩膜生成前，修复 float64 意外提升并限制 BLAS 线程。90 次无人画面采样没有超过 0.5 s，详见 [性能排查与验证](PERSON_PIPELINE_PERFORMANCE.md)。下文先前的延迟采样属于修复前记录。

目标板：S100，工作区 `/home/sunrise/luka_ws`。仅在新工作区修改；旧 `/home/sunrise/luka_s100` 未修改。本次只做不移动验收。

## 已接通的数据链路

`Astra Pro Plus 对齐 RGB-D → 原 YOLO26 HBM/BPU 人物分割 → 原页面 ConservativeTracker/身份锁定 → selected_bridge → ai_msgs/PerceptionTargets → D-Robotics tros_person_following → Nav2 NavigateToPose`

只把页面 `selected_track_id` 对应的清晰、可见、无关联歧义的人传给官方跟随节点，保持页面 track ID。其他人即使置信度更高，也不会进入跟随输入。沿用原页面的身份恢复逻辑；不把官方 IOU MOT 误称为 ReID。

官方 `hobot_mot` 已编译，但此链路不再运行第二层 MOT，避免把页面已经锁定的 ID 重新编号。当前 Humble Nav2 没有 `nav2_following`，本次使用官方代码实际依赖的 `NavigateToPose`，没有虚构 Following Server。

## 分割深度

在人物分割掩膜内，筛选 `isfinite(depth) && depth > 0` 的已对齐公制深度像素，然后计算 `Z = sum(depth) / 有效像素数`，严格采用算术平均，不回退到框深度、姿态估深或中位数。

- 最少 30 个有效像素，且至少占掩膜像素的 10%。
- RGB/深度时间差不能超过 50 ms；桥接时帧龄加 HTTP 请求耗时不能超过 0.5 s。
- 记录有效像素数、比例、标准差、质心和三维点。平均深度是光轴 Z，不是到人物的欧氏距离。
- 使用有效掩膜像素质心、真实相机内参和畸变系数得到光学坐标点，再通过驱动 TF 转为 `camera_link`。官方 `x_cm/y_cm` 分别是前方/左方厘米坐标。
- 框的投影宽高仅用于官方尺寸过滤，不参与深度平均。

官方初选要求置信度至少 0.7、投影宽至少 0.3 m、高至少 0.5 m；输入前方范围 0.1–4.0 m、横向 ±3.0 m。适配层提前应用这些条件，避免拒绝目标后启动搜索。

## 相机外参

用户确认相机位于车体正中心，离地 0.70 m，水平朝正前方。独立 `astra_body_mount` 发布：

`base_footprint → camera_link: translation=(0,0,0.70) m, roll=pitch=yaw=0`

这里 `base_footprint` 指地面投影坐标系；没有把 0.70 m 直接当作相对 `base_link` 的高度。驱动继续发布相机内部深度/RGB/光学坐标变换。后续如果 URDF 已发布同一安装变换，启动时设置 `publish_camera_mount:=false`，保持一个父子变换只有一个发布者。

真人调试时发现原底盘只有 `odom → base_link`；其 RS485 里程计明确设置 z=0。启动文件现已补充零偏移 `base_link → base_footprint`，完成到相机的连接。已使用相同安装 TF 在隔离 ROS 域重新验证；现有手动 launch 需要退出重启才能加载。若以后更换为带实际高度/倾斜的车体坐标定义，应重新配置地面投影变换。

## 跟随启停与行为

默认 `dry_run:=true`，官方控制器默认停用；启动不会控制轮子。

- 速度：`/luka_follow_dryrun/cmd_vel`。
- 导航 action：`/luka_follow_dryrun/navigate_to_pose`。
- 状态：`/luka_person_following/adapter_status`。
- 输入：`/luka/selected_seg_targets`。
- 对外启停服务：`/luka_person_following/set_enabled`。

人物丢失、弱/歧义关联、无效分割深度、画面过期、目标换 ID、缺少 map/车体/相机 TF，都会停用跟随。先完成取消再向官方节点送空目标或新 ID；重新出现后需要重新启用。关闭官方 IDLE 自转搜索，不在无人时自动寻找其他人。不要直接调用内部 `official/enable_follow` 绕过这些条件。

官方控制器保留“目标发生移动后才初选”的行为；不是点选静止人物就立即发导航。参数距离区间为 1.8–2.0 m、滞回 0.1 m。该版本把导航目标设为人物所在可通行位置，依靠实时距离条件取消导航；它没有实现严格固定偏移的跟随目标，不能据此宣称已经验证固定安全间距。

## 当前不移动启动

预览服务已安装、已启动，未设置开机自动启用：

```bash
sudo systemctl start luka-ws-orbbec-camera luka-ws-people
sudo systemctl start luka-ws-person-follow-preview
source /home/sunrise/luka_ws/system/environment.bash
ros2 topic echo /luka_person_following/adapter_status
```

预览没有真正 Nav2 action server，所以即使将来手动打开预览跟随，也只会输出隔离结果，不会驱动车体。当前现场无人、页面未选人，合法状态是空 targets、`enabled_applied=false`。缺少真实 map→base TF 时启用请求也会被拒绝。

停止预览：`sudo systemctl stop luka-ws-person-follow-preview`。

## 后续允许移动时的启动方式（本次未执行）

先按工作区 `docs/MIGRATION_AND_STARTUP.md` 启动车体、定位、Nav2，确认真实 map→base_footprint、相机安装 TF、全局代价地图和 `/navigate_to_pose` 正常；实车应有清空区域和急停操作员。再停止预览服务，避免重复启动节点：

```bash
sudo systemctl stop luka-ws-person-follow-preview
source /home/sunrise/luka_ws/system/environment.bash
ros2 launch luka_person_following selected_follow.launch.py dry_run:=false
```

另一终端在页面点选当前人后，明确启用：

```bash
source /home/sunrise/luka_ws/system/environment.bash
ros2 service call /luka_person_following/set_enabled std_srvs/srv/SetBool '{data: true}'
```

看 `adapter_status` 中 `enabled_applied` 确认控制器已处理请求。停用：

```bash
ros2 service call /luka_person_following/set_enabled std_srvs/srv/SetBool '{data: false}'
```

底盘另有 `/nx/navigation_enable` 许可开关。该官方跟随使用 Nav2，定位及传感器就绪后需要这个导航许可；原 `/nx/follow_enable` 是另一条旧速度跟随通道，不应混用。

真人测试记录：曾返回 `stale_frame`，随后连续 35 次实际采样的帧龄加 HTTP 耗时为 0.195–0.459 s，均在 0.5 s 限制内。检测 ID=4，seg 平均深度约 2.55 m、有效比例约 95.8%。当时页面 `selected_track_id=null`，适配原因已恢复为 `unselected`；AMCL 尚无 map→odom。必须点选目标并按真实地图位置设置初始位姿，不能靠放宽过期阈值或伪造 map TF 启用跟随。这个单次距离读数未和人工量距对照，不能视为精度验收。

## 验收证据

`evaluator/test_seg_depth_geometry.py`：7 个测试通过，覆盖算术平均与中位数差异、掩膜外背景排除、无效像素、无掩膜不回退、像素不足、时间差与三维投影。

`evaluator/test_selected_observation.py`：选定人隔离、未选/过期、弱/歧义/无效深度、禁止框深度回退、官方过滤条件。

`evaluator/static_follow_acceptance.py`：仅 ROS_DOMAIN_ID=88，模拟人物、模拟 TF、空闲代价地图和模拟 Nav2 action；证明选定 ID=12 的数据被正确接收、光学坐标转前方坐标、官方发导航、低于 1.8 m 取消并输出零速度、深度无效取消、恢复需重新启用、换人停用、过期送空目标。真实 `/cmd_vel` 和真实导航 action 均不在该测试链路中。

`evaluator/official_follow_acceptance_20261004/results.json` 和 `launch.log` 保存上述证据；`live_results.json` 保存真实相机与 BPU 检查。实时检查看到约 8 FPS、公制深度可用、BPU HBM 生效、仅 person 类、控制器停用、真实 `/cmd_vel` 无发布者。编译期间识别内存保护曾主动停止进程；编译完成后已恢复并重新验收。

现场无人，因此未验证真人分割区域的实际测距误差，也未做实车移动、避障、固定距离或遮挡重识别验收。模拟 TF 不会进入实际 ROS 域。

## 文件与官方来源

- `control/luka_person_following`：本次新增适配包和启动文件。
- `perception/person_follow/seg_depth_geometry.py`：分割深度计算。
- `perception/person_follow/worker.py`：仅新增 YOLO26 分割深度分支，原其他分支保留。
- `control/tros_person_following`：[官方仓库](https://github.com/D-Robotics/tros_person_following)，基线 commit `202e8c8a04dc41e3d3771daa131b852cc24f7c0d`。只增加 `navigate_to_pose_action_name` 参数，让隔离/真实 action 名称明确可配；跟随算法未重写。
- `perception/hobot_mot`：[官方 MOT](https://github.com/D-Robotics/mot)，commit `0120205146d88c3474bfc2936522e349e169fa8d`，已构建但不启动。
- `common/vendor/ai_msgs`：[官方消息](https://github.com/D-Robotics/hobot_msgs)，commit `ca63ebb7379862a6c307d17b0b86bd7096a1656d`。
- 原 worker 备份：`/home/sunrise/luka_migration_backups/official_follow_seg_20261004/perception/person_follow/worker.py`。

模型仍是原 `/home/sunrise/yolo26m-objv1-seg.pt` 转出的 YOLO26 HBM；没有重训、没有替换为其他模型、没有迁入 Odin、没有修改旧工作区。

## CPU 人脸关闭（用户要求）

`luka-ws-people.service.d/face-disabled.conf` 持久设置 `NX_FACE_ENABLED=0`。worker 不构建 YuNet/SFace 模型、不做人脸计数和特征识别，人脸录入/补录/完成录入请求直接拒绝。已有身份数据库保留；当前跟随仍按页面选择的人体 track ID 工作。OpenCV 线程数从 2 调为实测更快的 1；OSNet 人体外观描述仍保留，它不是人脸模型。

已重启并确认 `face_recognition={enabled:false,loaded:false}`、YOLO26 BPU 和分割深度正常。无人画面 45 次采样中，识别约 5.48 FPS，帧龄加 HTTP 耗时中位数 0.392 s，最大 0.545 s，仍有 4 次超过 0.5 s；关闭人脸不等于已完成真人时效稳定性验收。记录在 `evaluator/face_disabled_acceptance_20261004.json`。时效保护没有放宽。
