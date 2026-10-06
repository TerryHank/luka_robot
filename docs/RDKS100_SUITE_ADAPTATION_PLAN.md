# RDK S100 Suite 适配执行计划

> Repository: `TerryHank/luka_ws`  
> Working branch: `feat/rdks100-suite-adaptation`  
> Base branch: `main`  
> Target: 将当前 Luka S100 工程收敛为“D-Robotics 官方基础能力层 + Luka 产品/业务层”，在不破坏现有可运行能力的前提下逐层替换重复基础设施。

---

## 0. 总目标与硬约束

### 0.1 最终目标

最终运行链路收敛为：

```text
Astra Pro Plus RGB-D
        │
        ▼
D-Robotics YOLO26 / RDK Model Zoo S / S100 BPU
        │
        ▼
Luka Seg-Depth + Target Manager
        │
        ▼
ai_msgs/PerceptionTargets
        │
        ├─────────────► D-Robotics MOT（自动跟随模式，可选）
        │
        ▼
Luka Target Gate
        │
        ▼
D-Robotics tros_person_following
        │
        ▼
Nav2
        │
        ▼
Luka Navigation Safety
        │
        ▼
ddsm_car_control
        │
        ▼
DDSM Motors
```

语音/Agent 链路：

```text
Mic
 │
 ▼
sherpa-onnx KWS
 │
 ▼
Dialogue FSM
 │
 ▼
sensevoice_ros2
 │
 ▼
Luka nav_llm_agent
 │
 ├── hobot_xlm / hobot_llamacpp
 │
 └── Ollama fallback
 │
 ▼
hobot_tts / existing TTS fallback
 │
 ▼
Speaker
```

### 0.2 必须保留的 Luka 产品资产

不得因为“官方化”而删除或重写以下能力：

- `control/ddsm_car_control`
- `map/hotel_semantic_map`
- `map/hotel_semantic_map_msgs`
- `perception/spatial_memory`
- `system/nav_llm_agent` 的业务编排/能力注册/楼层/电梯/巡航逻辑
- Dashboard / 客户页 / 产品账号与业务数据库
- 当前 Segmentation Depth 几何算法
- 当前跟随 fail-closed 安全策略
- Nav2 自定义安全链，例如 `/nx/nav_guarded -> /nx/nav_safe`
- Orbbec Astra Pro Plus 驱动
- RPLidar / IMU / robot_localization / AMCL / SLAM Toolbox

### 0.3 禁止事项

- 禁止直接覆盖 `main`。
- 禁止直接删除当前 `tros_person_following` 本地 patch。
- 禁止未通过 dry-run 验收就向真实 `/cmd_vel` 或真实 `/navigate_to_pose` 发控制。
- 禁止把 Dashboard/HTTP 作为最终机器人控制数据源。
- 禁止把 `track_id` 当作永久人体身份 ID。
- 禁止提交任何 Token、密码、Cookie、SSH 私钥、设备密钥、数据库密码。
- 禁止为了“全官方”降级开放词汇找物能力为单纯 COCO80。
- 禁止为了官方组件替换已经稳定工作的 Astra RGB-D 厂商驱动。

---

# 1. 分支策略与提交策略

## 1.1 当前工作分支

```text
feat/rdks100-suite-adaptation
```

所有 Suite 适配工作都只在此分支完成。

## 1.2 推荐提交粒度

每个阶段至少一个独立 commit：

```text
chore(suite): add rdks100 suite baseline and dependency manifest
refactor(perception): introduce official yolo26 runtime adapter
refactor(perception): publish perception targets directly over ros2
refactor(follow): reduce luka_person_following to target gate
feat(voice): add sensevoice backend
feat(llm): add hobot xlm backend abstraction
test(suite): add dry-run acceptance and regression suite
docs(suite): document rollout and rollback
```

## 1.3 PR 原则

完成 P0~P8 后再从：

```text
feat/rdks100-suite-adaptation
        ↓
main
```

发 Draft PR。

在真实运动验收前保持 Draft。

---

# 2. Phase 总览

| Phase | 目标 | 风险 | 是否允许真实运动 | 完成标志 |
|---|---|---:|---:|---|
| P0 | 基线冻结、清点现状 | 低 | 否 | 有可复现 inventory |
| P1 | D-Robotics 依赖清单与版本锁定 | 低 | 否 | `.repos` + patch 说明 |
| P2 | YOLO26 Runtime 官方化 | 中 | 否 | 输出与性能回归通过 |
| P3 | 人体链路 ROS 化，去 HTTP 回环 | 中 | 否 | ROS 原生链工作 |
| P4 | Target Manager / Target Gate 收敛 | 中 | 否 | 安全逻辑独立 |
| P5 | MOT 双模式接入 | 中 | 否 | manual/auto 两种模式可切 |
| P6 | tros_person_following + Nav2 收敛 | 高 | 仅 dry-run | 官方跟随链验收 |
| P7 | Voice Suite 适配 | 中 | 否 | KWS/ASR/TTS 分层 |
| P8 | LLM Backend 适配 | 中 | 否 | hobot_xlm/llamacpp 可切换 |
| P9 | 找物/VLM 保留兼容 | 低 | 否 | 现功能无回归 |
| P10 | 实车灰度与主干合并 | 高 | 是 | 全链现场验收 |

---

# 3. P0 — 冻结当前基线

## 3.1 目标

在改代码前，记录当前分支的真实运行状态，避免后续“能跑但不知道哪里退化”。

## 3.2 Codex 操作

检查并生成：

```text
docs/suite/
├── baseline_inventory.md
├── baseline_topics.txt
├── baseline_services.txt
├── baseline_actions.txt
├── baseline_tf.txt
├── baseline_packages.txt
└── baseline_performance.md
```

采集：

```bash
source /home/sunrise/luka_ws/system/environment.bash

ros2 pkg list
ros2 topic list -t
ros2 service list -t
ros2 action list -t
ros2 node list
ros2 run tf2_tools view_frames
```

同时记录：

- Astra RGB / Depth topic
- CameraInfo
- registered depth 状态
- TF: `map -> odom -> base_link -> base_footprint -> camera_link -> optical_frame`
- YOLO26 HBM 路径
- 当前检测 FPS
- BPU forward latency
- CPU postprocess latency
- 人体 worker 总周期
- `tros_person_following` 参数
- Nav2 planner/controller
- `/nx/nav_guarded`
- `/nx/nav_safe`
- `ddsm_car_control`
- 当前语音 KWS / ASR / TTS backend
- 当前 LLM backend

## 3.3 验收

必须与现有文档数据一致或解释差异：

- YOLO26 BPU 正常
- person-only 路径正常
- Seg Depth 可用
- preview 跟随默认不控制真实底盘
- 当前 `main` 工作区不受影响

---

# 4. P1 — 建立 D-Robotics Suite 依赖层

## 4.1 新增目录

```text
vendor/drobotics/
├── rdks100-suite.repos
├── PATCHES.md
├── VERSION_LOCK.md
└── README.md
```

## 4.2 首批官方依赖

`rdks100-suite.repos` 至少包含：

- `D-Robotics/tros_person_following`
- `D-Robotics/mot`
- `D-Robotics/hobot_msgs`
- `D-Robotics/hobot_dnn`
- `D-Robotics/sensevoice_ros2`
- `D-Robotics/hobot_tts`
- `D-Robotics/hobot_xlm`
- `D-Robotics/hobot_llamacpp`

模型工具链单独记录：

- `D-Robotics/rdk_model_zoo_s`
- branch: `s100`

## 4.3 版本规则

开发阶段允许从官方 `develop` / `s100` 对比最新代码。

进入验收前必须将全部依赖锁到 commit SHA。

禁止生产运行直接漂移在 `develop`。

## 4.4 tros_person_following 本地 patch

当前 Luka 版本保留：

```text
navigate_to_pose_action_name
```

原因：

- dry-run 需要 `/luka_follow_dryrun/navigate_to_pose`
- real 需要 `/navigate_to_pose`

在 `PATCHES.md` 中明确记录：

```text
upstream:
D-Robotics/tros_person_following

local patch:
configurable NavigateToPose action name

status:
required until upstream supports equivalent configuration
```

不要直接删掉本地 patch。

## 4.5 验收

- 能通过 `vcs import` 拉取依赖。
- 能完整记录每个 upstream SHA。
- 未修改运行逻辑。

---

# 5. P2 — YOLO26 Runtime 官方化

## 5.1 当前问题

当前路径：

```text
perception/person_follow/
├── bpu_yolo26_runtime/
├── yolo26_bpu_person.py
├── worker.py
└── seg_depth_geometry.py
```

模型本身已经是 S100 HBM，但 Runtime 与后处理主要由 Luka 自己维护。

## 5.2 目标结构

新增：

```text
perception/person_follow/runtime/
├── base.py
├── luka_legacy.py
├── drobotics_yolo26.py
└── factory.py
```

统一接口示例：

```python
class PersonSegmenter:
    def infer(self, frame):
        """
        return:
          boxes
          scores
          class_ids
          masks
          timing
        """
```

backend：

```text
legacy
drobotics
```

配置：

```yaml
person_detector:
  backend: drobotics
  model: /.../yolo26m_objv1_seg_bpu_nashe_640x640_nv12.hbm
  class_id: 0
```

## 5.3 必须保留

以下逻辑继续归 Luka：

- person class filter
- Seg mask
- registered RGB-D
- invalid depth filtering
- trim ratio
- `seg_valid_trimmed_mean`
- XYZ geometry
- depth quality diagnostics

## 5.4 双后端回归

同一帧输入：

```text
legacy runtime
      │
      ├── bbox
      ├── score
      └── mask

drobotics runtime
      │
      ├── bbox
      ├── score
      └── mask
```

比较：

- bbox IoU
- score 差异
- mask IoU
- person 数量
- Seg Depth
- XYZ
- forward latency
- postprocess latency

## 5.5 性能门槛

不能明显差于当前基线：

- BPU forward 约 20~30ms 级
- 无人画面后处理不能重新退化到百毫秒级
- 不允许恢复 float64 mask 计算
- BLAS 线程限制保持合理

## 5.6 验收

- `backend=legacy` 原行为不变。
- `backend=drobotics` 输出通过对比。
- 默认仍先保持 legacy，直到 P3 验收完成。
- 不允许真实运动。

---

# 6. P3 — 去除人体控制链 HTTP 回环

## 6.1 当前链路

```text
person worker
 ↓
HTTP /api/people/follow-state
 ↓
luka_person_following/bridge.py
 ↓
ai_msgs/PerceptionTargets
```

最终不应让 Web API 成为机器人控制数据源。

## 6.2 目标链路

```text
YOLO26
 ↓
Person Perception ROS Node
 │
 ├── /luka/perception/person_targets
 ├── /luka/perception/person_diagnostics
 └── /luka/perception/selected_track
          ↓
     Target Gate
          ↓
/luka/follow/selected_target
          ↓
tros_person_following
```

## 6.3 消息约定

检测输出统一：

```text
ai_msgs/msg/PerceptionTargets
```

不得再定义重复的内部 detection message。

Luka 私有状态如果必须额外表达，可使用：

```text
/luka/perception/person_diagnostics
/luka/perception/selected_track
```

但检测本体必须使用 `ai_msgs`。

## 6.4 Dashboard 改造原则

旧：

```text
Dashboard
  ↕
HTTP State
  ↓
Robot Control
```

新：

```text
ROS2
 ↓
Dashboard adapter
 ↓
HTTP/WebSocket
 ↓
Dashboard
```

网页只做：

- 显示
- 用户选择目标
- 发“选择 ID / 启停”命令

不再负责产生机器人所需的核心观测。

## 6.5 兼容窗口

在一个过渡版本中保留旧：

```text
/api/people/follow-state
```

但改为 ROS 数据的只读镜像。

禁止 ROS 反过来轮询它。

## 6.6 验收

- 关闭 HTTP 服务后，ROS 跟随 dry-run 仍能得到目标。
- Dashboard 挂掉不会导致 ROS 感知链停止。
- HTTP 接口只作为观察/兼容层。
- 不允许真实运动。

---

# 7. P4 — 将 luka_person_following 缩薄为 Target Gate

## 7.1 新职责

当前 `control/luka_person_following` 不删除，而是重构为：

```text
Luka Target Gate
```

只负责：

- 用户选定目标
- stale frame
- weak observation
- ambiguity
- selected missing
- Seg Depth valid
- depth jump
- TF available
- track changed
- follow enable permission
- fail closed
- diagnostics

## 7.2 不再负责

- 不再轮询 HTTP。
- 不再二次推理。
- 不再自行做运动控制。
- 不再自己实现 Nav2 following。

## 7.3 Topic

建议标准化：

```text
input:
/luka/perception/person_targets

selection:
/luka/target_manager/selected_track_id

output:
/luka/follow/selected_target

status:
/luka/follow/target_gate_status

service:
/luka/follow/set_enabled
```

## 7.4 安全原则

任意以下条件必须立即 fail closed：

```text
stale_frame
selected_missing
selected_ambiguous
weak_observation
invalid_seg_depth
depth_jump
tf_unavailable
track_id_changed
source_unavailable
```

## 7.5 验收

为以上每个 fail-close 条件写单测。

必须覆盖：

- 空目标
- 新 ID
- 同一 ID 短时 depth invalid
- 超时 depth invalid
- depth jump
- TF 丢失
- 服务取消
- 重启后默认 disabled

---

# 8. P5 — MOT 双模式设计

## 8.1 原则

官方 `D-Robotics/mot` 当前主要是 IOU/Kalman MOT。

不能把 `track_id` 当永久身份。

## 8.2 两种运行模式

### Mode A — automatic

```text
YOLO26
 ↓
D-Robotics tros_mot_node
 ↓
Target selection
 ↓
tros_person_following
```

用途：

- Demo
- 单人场景
- 自动选人
- 快速体验

### Mode B — selected/identity

```text
YOLO26
 ↓
MOT
 ↓
Luka Target Manager
 ↓
user selection / identity / future ReID
 ↓
Target Gate
 ↓
tros_person_following
```

用途：

- “跟着这个人”
- 多人场景
- 酒店产品模式

## 8.3 配置

```yaml
follow:
  tracking_mode: selected
  # selected | automatic
```

## 8.4 验收

- 多人时 manual selection 不被官方 MOT 自动覆盖。
- official MOT ID 改变时 selected 模式 fail closed。
- automatic 模式可以正常选择候选。
- ReID 未启用时文档明确“不保证跨长遮挡恢复原身份”。

---

# 9. P6 — tros_person_following + Nav2 收敛

## 9.1 目标

保留 D-Robotics 官方跟随状态机作为唯一跟随控制核心。

Luka 不重新实现 P/PID 跟随控制器。

## 9.2 保留参数

至少显式管理：

- `follow_distance_min`
- `follow_distance_max`
- `follow_hysteresis`
- `follow_goal_pub_rate`
- `follow_goal_dist_deadzone`
- `follow_goal_yaw_deadzone`
- `tracking_to_lost_timeout_sec`
- `lost_to_idle_timeout_sec`
- `idle_search_total_timeout_sec`
- `target_filter_range_x_max`
- `target_filter_range_y_min`
- `target_filter_range_y_max`
- `navigate_to_pose_action_name`（Luka patch）

## 9.3 dry-run

必须继续保留：

```text
/luka_follow_dryrun/navigate_to_pose
/luka_follow_dryrun/cmd_vel
```

真实运行：

```text
/navigate_to_pose
/cmd_vel or protected command path
```

## 9.4 Luka Safety

真实运动前确认：

```text
tros_person_following
        ↓
Nav2
        ↓
velocity smoother
        ↓
Luka navigation guard
        ↓
collision monitor / safety
        ↓
ddsm_car_control
```

禁止官方节点直接绕过安全链驱动 DDSM。

若 `tros_person_following` 的 `/cmd_vel` 原地搜索会绕过 Nav2，则必须 remap 到 Luka 安全输入。

## 9.5 dry-run 验收

模拟：

- 正常人物
- 目标接近
- 目标远离
- 目标丢失
- target ID change
- Seg Depth invalid
- Nav2 goal send
- Nav2 goal cancel
- LOST
- recovery
- IDLE

真实：

```text
/cmd_vel
```

必须没有危险输出。

## 9.6 实车前置条件

只有全部满足才允许 P10：

- map / odom / base TF 正常
- AMCL 正常
- costmap 正常
- 激光正常
- emergency stop 可用
- 人工操作员在场
- 首次速度上限低速
- 空旷测试区

---

# 10. P7 — Voice Suite 适配

## 10.1 不替换整个 voice_gateway

当前 `voice_gateway.py` 已经包含有效产品逻辑。

拆分成：

```text
voice/
├── audio_frontend
├── kws_backend
├── asr_backend
├── dialogue_fsm
├── tts_backend
└── ros_gateway
```

## 10.2 KWS

继续使用现有：

```text
sherpa-onnx
```

至少第一阶段不换。

## 10.3 ASR

增加 backend：

```text
existing_sherpa_sensevoice
drobotics_sensevoice_ros2
```

统一输出：

```text
/voice/recognized_text
```

## 10.4 TTS

增加：

```text
existing
hobot_tts
```

保留 fallback。

## 10.5 AEC

在 Suite 迁移完成后追加：

```text
speaker reference
        │
        ▼
WebRTC AEC
        ▲
        │
Mic ────┘
 ↓
VAD
 ↓
ASR
```

目标是真正支持用户打断，而不是仅 `tts_echo_guard` 暂停录音。

## 10.6 验收

- 唤醒词“露卡”
- 语音识别
- TTS
- 不自激唤醒
- TTS 播放期间状态机正确
- backend 切换不影响 `nav_llm_agent`

---

# 11. P8 — LLM Runtime 官方化

## 11.1 保留 nav_llm_agent

不删除：

```text
system/nav_llm_agent
```

保留：

- capability registry
- workflow engine
- hotel semantic map interaction
- floor transfer
- elevator
- patrol
- navigation
- cancel
- tool schema
- task state

## 11.2 新建 LLM Backend 抽象

建议：

```text
system/nav_llm_agent/nav_llm_agent/llm/
├── base.py
├── ollama_backend.py
├── hobot_xlm_backend.py
├── hobot_llamacpp_backend.py
└── factory.py
```

统一接口：

```python
class LLMBackend:
    def generate(self, messages, tools=None):
        ...
```

## 11.3 Backend 优先顺序

目标配置：

```yaml
llm:
  backend: hobot_xlm
  fallback:
    - hobot_llamacpp
    - ollama
```

## 11.4 重要原则

LLM 只负责：

```text
Natural Language
      ↓
Structured Tool Call
```

机器人安全决策不能交给 LLM。

运动必须继续经过：

```text
Capability Registry
Workflow
ROS Action/Service
Safety Gate
```

## 11.5 验收

用当前 capability 测试集回归：

- 导航
- 巡航
- 取消
- 电梯
- 楼层
- 酒店地点
- 问候
- 非法工具调用
- 超时
- malformed JSON
- backend crash
- fallback

---

# 12. P9 — Object / YOLOE / Spatial Memory

## 12.1 暂不降级

保留：

- `perception/yoloe26_live`
- `perception/locateanything_trial_20260907`
- `perception/spatial_memory`
- `perception/object_api/s100_object_api.py`

## 12.2 Object API 内部官方化

可做：

```text
HTTP Object API
      ↓
ObjectService
      ↓
D-Robotics Runtime Adapter
      ↓
S100 BPU
```

但外部兼容 API 保持不变。

## 12.3 官方开放词汇替换条件

只有同时达到以下条件才替换 YOLOE：

- 文本开放词汇
- S100 BPU
- 多类别动态查询
- 与现 Dashboard/Agent API 兼容
- 现场精度不下降
- 性能满足实时要求

否则继续保留现有实现。

---

# 13. P10 — 实车灰度

## 13.1 Stage 1

轮子悬空：

- 跟随启停
- cmd_vel 方向
- 取消
- emergency stop
- target lost

## 13.2 Stage 2

地面低速：

建议临时限制：

```text
linear <= 0.15~0.20 m/s
angular <= 0.3~0.4 rad/s
```

测试：

- 单人直行
- 单人左右移动
- 停止
- 接近
- 远离
- 短遮挡

## 13.3 Stage 3

多人：

- 用户选 A
- B 穿过
- A/B 交叉
- A 离开
- A 回来
- ID change
- 禁止误跟 B

## 13.4 Stage 4

Nav2 场景：

- 走廊
- 转角
- 门口
- 障碍物
- costmap update
- 人走到障碍物后
- person goal free-cell

## 13.5 Stage 5

长时间稳定性：

至少记录：

- CPU
- BPU
- memory
- thermal
- FPS
- latency
- target loss
- MOT ID switches
- Nav2 cancel count
- safety stop count

---

# 14. 推荐最终目录

不要求一次性移动所有文件，待功能稳定后再做物理目录整理。

目标：

```text
luka_ws/
├── luka/
│   ├── bringup/
│   ├── base/
│   │   └── ddsm_car_control/
│   ├── perception/
│   │   ├── target_manager/
│   │   ├── seg_depth/
│   │   ├── identity/
│   │   ├── spatial_memory/
│   │   └── object_api/
│   ├── navigation/
│   │   ├── hotel_semantic_map/
│   │   └── navigation_guard/
│   ├── agent/
│   ├── voice/
│   └── product/
├── vendor/
│   └── drobotics/
├── config/
├── models/
├── maps/
├── launch/
├── docs/
└── evaluator/
```

现阶段不要为了目录美观提前大搬家。

---

# 15. Codex 每阶段必须执行的工作方式

每个 Phase 均按以下顺序：

1. 先读现有源码和测试。
2. 写出当前真实数据流。
3. 只修改最小必要范围。
4. 增加兼容开关。
5. 保留旧 backend。
6. 编译。
7. 静态测试。
8. dry-run。
9. 对比 baseline。
10. 输出修改清单。
11. 输出未完成项。
12. 单独 commit。

不得“顺便”重构无关模块。

---

# 16. 编译与测试基线

每次修改后至少执行：

```bash
source /opt/tros/humble/setup.bash
source /opt/ros/humble/setup.bash || true

cd /home/sunrise/luka_ws

colcon build --symlink-install   --packages-select   luka_person_following   tros_person_following   nav_llm_agent   ddsm_car_control   hotel_semantic_map   hotel_semantic_map_msgs
```

实际包名以当前 workspace 为准。

Python：

```bash
python3 -m compileall   perception   control   system/nav_llm_agent
```

针对现有 evaluator 增加 Suite 专用：

```text
evaluator/suite/
├── test_yolo_runtime_parity.py
├── test_seg_depth_parity.py
├── test_ros_person_pipeline.py
├── test_target_gate.py
├── test_mot_modes.py
├── test_follow_dryrun.py
├── test_voice_backends.py
└── test_llm_backends.py
```

---

# 17. 关键验收指标

## Vision

- 人体 BPU forward 不明显退化。
- Seg mask 输出与旧版一致。
- depth 不使用 bbox 背景替代。
- stale frame fail closed。
- Dashboard 挂掉不影响 ROS 感知。

## Follow

- 未选人不动。
- depth invalid 不动。
- TF invalid 不动。
- ID change 不自动换人。
- LOST 不误跟其他人。
- dry-run 不产生真实运动。

## Navigation

- 全部速度必须经过 Luka safety chain。
- `ddsm_car_control` 不直接接收未保护的外部运动源。
- Nav2 cancel 能在目标失效后及时执行。

## Voice

- KWS/ASR/TTS backend 可替换。
- Agent 输入接口不随 backend 改变。
- TTS 不触发自唤醒。

## Agent

- LLM backend crash 时不产生运动。
- malformed tool call 不执行。
- capability registry 仍是动作白名单。

---

# 18. 回滚策略

任何 Phase 出现问题：

```text
配置切回 legacy backend
        ↓
重启对应服务
        ↓
恢复上一阶段 commit
```

禁止通过删除旧实现来逼迫新实现上线。

直到 P10 完成，保留：

- legacy YOLO backend
- existing ASR backend
- existing TTS backend
- Ollama backend
- 当前 HTTP 只读兼容 API

---

# 19. 本分支首要执行顺序

Codex 从本文件开始后，严格按以下任务依次执行：

```text
[x] P0 生成 baseline inventory
[x] P1 创建 vendor/drobotics/rdks100-suite.repos
[x] P1 锁定 D-Robotics upstream SHA
[x] P1 记录 tros_person_following 本地 patch
[ ] P2 抽象 YOLO26 runtime
[ ] P2 接入 rdk_model_zoo_s runtime
[ ] P2 完成 legacy/drobotics parity test
[ ] P3 ROS 原生发布 ai_msgs/PerceptionTargets
[ ] P3 将 HTTP follow-state 改为只读镜像
[ ] P4 重构 luka_person_following 为 Target Gate
[ ] P4 完成 fail-close 单测
[ ] P5 接入 official MOT automatic 模式
[ ] P5 保留 selected 模式
[ ] P6 完成 official follow dry-run
[ ] P6 确认所有速度经过 Luka safety chain
[ ] P7 增加 sensevoice_ros2 backend
[ ] P7 增加 hobot_tts backend
[ ] P8 抽象 LLMBackend
[ ] P8 接入 hobot_xlm
[ ] P8 接入 hobot_llamacpp fallback
[ ] P9 保持 YOLOE/LocateAnything 能力不降级
[ ] P10 轮子悬空测试
[ ] P10 地面低速测试
[ ] P10 多人交叉测试
[ ] P10 Nav2 场景测试
[ ] P10 长稳测试
[ ] 创建 Draft PR
[ ] 完成人工 review 后合并 main
```

---

# 20. 完成定义

只有以下全部成立，RDK S100 Suite 迁移才算完成：

1. S100 BPU 模型 Runtime 优先来自 D-Robotics 官方链路。
2. 人体控制链不再依赖 HTTP polling。
3. `ai_msgs` 成为感知标准接口。
4. D-Robotics MOT 可作为自动模式使用。
5. Luka Target Manager 保留“跟谁”的产品能力。
6. `tros_person_following` 成为唯一跟随状态机。
7. Nav2 继续作为移动导航核心。
8. 所有运动经过 Luka Safety。
9. Voice backend 与产品 Dialogue FSM 解耦。
10. LLM backend 与 `nav_llm_agent` 业务逻辑解耦。
11. Hotel / Memory / Product / Dashboard 功能无回归。
12. 实车多人物遮挡不会在 ID 改变后自动误跟陌生目标。
13. 有完整版本锁、回归测试、回滚路径和现场验收记录。


---

## 21. 分阶段执行记录

### P0 — 基线冻结

状态：**仓库侧完成，板端刷新待现场执行。**

- 已冻结现有仓库中的 S100、RGB-D、YOLO26 BPU、Seg Depth、Nav2、跟随、语音、LLM 证据。
- 已新增 `docs/suite/baseline_*`。
- 已新增只读 `system/scripts/capture_live_baseline.sh`，使用 `bash` 执行；不发布速度、不发送导航目标、不启用跟随。
- 当前执行环境没有 RDK S100 shell，因此没有伪造新的板端 ROS 图谱或性能数据。
- P0 未修改任何运行代码，未允许真实运动。


### P1 — 官方依赖与版本锁定

状态：**完成（仓库侧静态验证）。**

- 根目录 `vendor` 是指向 `common/vendor` 的兼容链接，因此实际文件放在 `common/vendor/drobotics/`，工作区仍可通过 `vendor/drobotics/` 访问。
- 已创建 SHA 锁定的 `rdks100-suite.repos`。
- 已记录 `tros_person_following` 的 `navigate_to_pose_action_name` Luka patch。
- 当前环境未运行 `vcs import`；manifest 使用标准 vcstool YAML，板端导入验证待现场补录。
- P1 未修改运行代码，未允许真实运动。
