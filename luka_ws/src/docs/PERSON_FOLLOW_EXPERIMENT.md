# Luka S100 人体跟随实验教程

适用日期：2026-10-08；当前工程 `/home/sunrise/luka_ws`。
采用已对齐官方策略的 S100 版本，继续使用当前 SLAM、Nav2 和底盘安全链。
本教程的整理过程没有启动实车运动。现有构建/模拟通过，真人和落地实验是后续验收。

## 实验分三阶段

| 阶段 | 启用什么 | 是否允许运动 | 本阶段通过条件 |
| --- | --- | --- | --- |
| A 人体感知 | 相机、分割、融合、MOT | 否，跟随算法关闭 | 看见person、合理ROI/深度、稳定短时track_id |
| B dry-run | 现有基础导航 + 跟随策略观察 | 否，底盘许可关闭、无运动Action | TRACKING、导航候选、旋转候选和明确诊断 |
| C 实车闭环 | nav2_action + 单独底盘跟随许可 | 是 | 跟随距离、转向、丢失恢复、停止与接管均实测 |

先完成A/B再进入C。首次实车使用一名目标和一名停止操作员，路径留出转身空间；先验停止操作，再试丢失后的旋转搜索。
跟随策略会在无目标时主动搜索，并可切换MOT编号；它不按人脸锁定指定身份。

## 0. 准备终端与停止入口

Windows PowerShell连接机器人：

```powershell
ssh sunrise@192.168.3.150
```

建议准备三个SSH终端：①跟随前台日志，②启停操作，③状态/反馈观察。
每个新Linux终端先执行：

```bash
cd /home/sunrise/luka_ws
source src/system/environment.bash
source src/system/scripts/person_follow_environment.bash
```

环境统一为生产 ROS domain 87；不使用模拟测试里的隔离domain。

**本教程使用一个前台跟随入口，不同时启动preview服务。** 查看：

```bash
systemctl is-active luka-ws-person-follow-preview.service
```

如该服务正在运行，先停止已有跟随/运动任务，再执行：

```bash
sudo systemctl stop luka-ws-person-follow-preview.service
```

若原来在另一终端前台运行跟随，应在原终端停止它；不要另起第二套分割/MOT/跟随节点。
不要使用 `src/system/luka.sh start ws full` 来准备本实验：该入口会启动可旋转的自动定位流程及其他任务服务。

### 实车实验时的停止命令

在操作终端执行，先停算法并撤销两类底盘许可：

```bash
ros2 service call /person_follow/enable_follow std_srvs/srv/SetBool '{data: false}'
ros2 service call /nx/follow_enable std_srvs/srv/SetBool '{data: false}'
ros2 service call /nx/navigation_enable std_srvs/srv/SetBool '{data: false}'
```

再看实测轮式里程计：

```bash
ros2 topic echo /wheel/odom --field twist.twist
```

应看到平面线速度接近0（小于0.02 m/s）、角速度接近0（小于0.05 rad/s），且消息仍新鲜。
服务回复成功只表示请求处理，不能替代实际停稳检查。ROS/SSH失联时使用现场物理停止/断电措施。
观看 `topic echo` 的Ctrl+C只结束观察；只有跟随前台终端的Ctrl+C才结束该跟随进程。
不向 `/cmd_vel` 或 `/nx/nav_safe` 手工注入速度，也不在底盘驱动运行时另开串口停止脚本。

## A. 先只验证人体感知

### A1. 启动或复用相机

```bash
sudo systemctl start luka-ws-orbbec-camera.service
ros2 topic hz /camera/color/image_raw
```

Ctrl+C退出频率观察，再看深度：

```bash
ros2 topic hz /camera/depth/image_raw
ros2 topic echo /camera/depth/image_raw --once --field header
```

相机应持续输出640×480注册RGB-D；不要启动另一套USB采集程序。

### A2. 在终端①启动唯一跟随链，保持算法关闭

```bash
bash src/system/scripts/start_official_person_following.sh \
  output_mode:=dry_run \
  follow_enabled_on_start:=false
```

这个入口启动分割、深度融合、MOT和跟随核心；本阶段不用启动人脸服务。
默认不启用跟随决策，因而只观察感知也不要求先放行底盘。

### A3. 在终端③观察真人

```bash
ros2 topic echo /tros_mot_targets --once --truncate-length 32
```

让一人站在相机前约2–3 m，尽量看见完整身体，缓慢左右移动约20–30 cm。
检查：

- `type: person`、ROI大小合理。
- `track_id` 在短时间可见期间稳定；不把它当永久身份。
- 融合属性有有限的 `x_cm/y_cm/width_cm/height_cm`；2–3 m前向距离通常对应约200–300 cm。
- 相机和MOT时间戳正常，没有长期停在一帧。

仅看到人体框不代表已满足导航跟随条件。置信度不足、尺寸不够或没有有效深度时，核心仍会拒绝选择。
若只显示椅子等非person，先处理人体感知；不要直接进入实车阶段。

## B. dry-run：不放行底盘，检查策略

### B1. 准备既有基础栈

已有生产导航栈在运行时复用它，不另开第二套。空闲状态下可以使用当前systemd入口：

```bash
sudo systemctl start luka-ws-hardware@sensors.service
sudo systemctl start luka-ws-hardware@manual_base.service
```

确认底盘串口只有现有控制进程占用。当前部署存在 `src/common/config/nx_manual_mode` 标记，定位入口会据此避免另启readonly串口里程计进程；若标记或启动方式以后变化，先核对所有者。

关闭运动许可：

```bash
ros2 service call /nx/follow_enable std_srvs/srv/SetBool '{data: false}'
ros2 service call /nx/navigation_enable std_srvs/srv/SetBool '{data: false}'
```

然后启动当前定位与导航：

```bash
sudo systemctl start luka-ws-hardware@localization.service
sudo systemctl start luka-ws-hardware@navigation.service
```

**地图必须对应当前场地。** 当前定位入口使用已有楼层地图；不要在错误地图上随便给一个0,0初始位姿。
通过现有定位面板/初始位姿工具设置真实位置和朝向，确认雷达与地图匹配、`map→base_link`稳定。
如果只有隔离RTAB-Map实验在运行，它的私有TF不能代替生产定位。

### B2. 检查Nav2、里程计和TF

```bash
ros2 lifecycle get /bt_navigator
ros2 lifecycle get /controller_server
ros2 lifecycle get /behavior_server
ros2 topic hz /wheel/odom
ros2 run tf2_ros tf2_echo map base_link
```

生命周期应为active；里程计应持续输出。
查看TF后Ctrl+C，再检查相机外参链：

```bash
ros2 run tf2_ros tf2_echo map camera_link
```

若相机TF缺失，补齐已测量的安装外参；不要用虚构的零位移/零旋转绕过检查。

执行只读预检：

```bash
ros2 run s100_person_following_integration preflight.py
```

预检必须正常退出，报告 `action_ready` 和 `spin_action_ready` 为true，所需话题各有唯一发布者、TF可查。
它是接口/拓扑检查，不是深度精度、实时新鲜度或实车安全的完整验收。还要检查A阶段的数据和下方诊断。

### B3. 确认模式并显式启用策略

```bash
ros2 param get /person_follow/tros_person_following_node output_mode
```

必须显示 `dry_run`。然后：

```bash
ros2 service call /person_follow/enable_follow std_srvs/srv/SetBool '{data: true}'
```

终端③分别观察（需要同时看时另开观察窗口）：

```bash
ros2 topic echo /person_follow/tros_tracking_status
ros2 topic echo /person_follow/integration_diagnostics
ros2 topic echo /person_follow/goal_candidate
```

一人从约2.5 m处缓慢移动，预期 `IDLE_OBSERVING → TRACKING` 并出现map坐标候选目标。
站着不动停在观察状态是正常策略：初选要求移动证据。
距离带为1.8–2.0 m，带回滞；进入跟随通常需要超过约2.1 m，不要把2.0 m理解为无回滞的精确开关。

无目标超过3 s时，观察旋转候选：

```bash
ros2 topic echo /person_follow/spin_candidate
```

它只显示计划朝向，dry-run不会下发真实Spin或导航目标，不能证明实际扫描已完成。
旋转候选也需要新鲜里程计停稳证据；缺失时看诊断原因。

### B4. Foxglove可视化建议

| 面板/图层 | 话题 |
| --- | --- |
| Image | `/camera/color/image_raw` |
| Raw Messages | `/tros_mot_targets` |
| 状态文本 | `/person_follow/tros_tracking_status`、`/person_follow/integration_diagnostics` |
| 3D，固定坐标map | `/person_follow/target_pose`、`/person_follow/goal_candidate`、`/person_follow/spin_candidate`、地图/TF |
| 里程计/速度观察 | `/wheel/odom`、`/nx/nav_safe` |

图像框、目标位姿、候选箭头、状态应相互一致。

## C. 受控实车闭环

仅在A/B通过、地图和定位正确、真人深度/时间戳/相机外参已确认后，进入本阶段。

### C1. 停掉dry-run进程并确认底盘仍未放行

```bash
ros2 service call /person_follow/enable_follow std_srvs/srv/SetBool '{data: false}'
ros2 service call /nx/follow_enable std_srvs/srv/SetBool '{data: false}'
ros2 service call /nx/navigation_enable std_srvs/srv/SetBool '{data: false}'
```

在终端①Ctrl+C结束dry-run跟随；保持当前基础栈运行。

### C2. 终端①启动Action模式，仍不自动启用

```bash
bash src/system/scripts/start_official_person_following.sh \
  output_mode:=nav2_action \
  input_contract_verified:=true \
  follow_enabled_on_start:=false
```

`input_contract_verified=true` 是操作者对现场输入已验收的声明，不是强行解除门控。
数据过期、地图未知、TF错误、动作服务器未就绪等保护仍然有效。

### C3. 先算法，后底盘

让目标提前站在相机前约2.5 m并缓慢移动。
在终端②先启用算法：

```bash
ros2 service call /person_follow/enable_follow std_srvs/srv/SetBool '{data: true}'
```

此时底盘许可仍关闭。确认状态为TRACKING，诊断有导航接受/反馈，现有出口持续有合适的控制输出：

```bash
ros2 topic echo /nx/nav_safe --once
```

确认其他导航、巡航、重定位任务已经结束，才手动放行更严格的底盘跟随通道：

```bash
ros2 service call /nx/follow_enable std_srvs/srv/SetBool '{data: true}'
```

必须回复 `success: true`。首次实验保留 `/nx/navigation_enable=false`，用更严格的follow通道接收Nav2输出。
该通道当前限制前进不超过0.40 m/s、倒退不超过0.12 m/s、角速度不超过0.50 rad/s，并保持现有近障检查。

**两个开关不能混淆：**`/person_follow/enable_follow`控制策略，`/nx/follow_enable`控制底盘接收许可。
底盘许可在0.6 s收不到跟随速度时撤销。先开底盘再等人移动，许可可能已经过期。
如果静止或任务间隙导致许可撤销，先查原因，确认仍适合继续后再手动放行；不要用循环反复自动开启服务来对抗看门狗。

### C4. 按顺序验收

| 次序 | 操作 | 观察结果 |
| --- | --- | --- |
| 1 | 缓慢直行移动目标 | TRACKING、Nav2反馈、真实里程计位移方向正确 |
| 2 | 目标停止/缓慢靠近 | 距离带内withhold，过近取消；实测底盘停稳 |
| 3 | 目标在近距离画面边缘移动 | TRACKING_EDGE_TURN、Spin反馈；实际转向把目标拉回视野 |
| 4 | 小幅短时遮挡 | WILL_BE_LOST，恢复可见后继续跟踪 |
| 5 | 目标暂时离开视野 | LOST观测点导航/扫描/轮次或超时；再出现通过门控恢复 |
| 6 | 发软件停止或现场手动接管 | 自有任务取消、实测停稳，许可不得自行重新打开 |

首次先验证1/2/6；停止确认可靠后再做3/4/5。
LOST阶段可能自主导航或旋转；8 s总搜索预算、最多2轮不保证现场每次完整完成两次扫描。
单人MOT变号桥接与附近新目标接受属于官方策略；首次不做多人交叉身份实验，也不能将SFace结果当作指定身份跟随保证。

## 常见卡点

| 现象/诊断 | 核查 |
| --- | --- |
| Already published / follower already exists | 同一链路重复启动；确认已有发布者归属后复用，不再起第二套 |
| IDLE_OBSERVING但不跟随 | 人未移动、初选置信度不足0.7、宽高或深度不合格 |
| BLOCKED stale input / TF / costmap | 检测和TF门限0.6 s、地图2 s；检查真实更新率与定位 |
| BLOCKED waiting for fresh measured stop | `/wheel/odom`过期、child_frame不是base_link、非有限值或机器人未停稳 |
| spin action server unavailable | behavior_server不active、`/spin`不存在或环境/domain不一致 |
| 相机/MOT有数据但没有候选 | 缺生产map/TF/costmap；隔离RTAB-Map不能代替生产接口 |
| TRACKING但小车不动 | 仍是dry_run、底盘许可未打开/已撤销、Nav2或碰撞/近障保护输出为零 |
| `/nx/follow_enable`返回false | 高低雷达任一过期、编码器反馈不健康或手动接管状态未释放 |

看基础服务日志：

```bash
journalctl -u luka-ws-hardware@manual_base.service -n 60 --no-pager
journalctl -u luka-ws-hardware@navigation.service -n 60 --no-pager
```

本轮跟随使用前台启动，核心日志直接在终端①。

## 记录结果与结束

需要记录时另开终端，采用少量状态/运动话题，先不录图像和带大分割mask的原始MOT。轻量target话题保留当前目标信息：

```bash
mkdir -p /home/sunrise/luka_data/recordings/bags
ros2 bag record \
  -o /home/sunrise/luka_data/recordings/bags/person_follow_$(date +%Y%m%d_%H%M%S) \
  /person_follow/target /person_follow/tros_tracking_status \
  /person_follow/integration_diagnostics /person_follow/target_pose \
  /wheel/odom /nx/nav_safe /tf /tf_static
```

结束顺序：停算法→撤销底盘两类许可→确认轮速接近0→跟随前台Ctrl+C→录包终端Ctrl+C。
无需为了结束本次跟随实验停止其他用途正在使用的相机或整套SLAM/Nav2。
记录每个用例的PASS/FAIL、对应日志、地图/定位条件和是否实测停稳；不要以构建或服务启动成功代替真人闭环通过。

