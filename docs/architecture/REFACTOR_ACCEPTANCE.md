# 架构迁移阶段记录

执行日期：2026-10-07。Git 目标为 `TerryHank/luka_ws` 的 `main`。本地源目录 `D:/Workspace/luka_ws`；S100 隔离候选目录 `/home/sunrise/luka_architecture_validation_20261007`。

## Phase 1–6

纯 Capability policy、dispatcher、Behavior Registry、Mission package、agent 统一入口及 Dashboard 执行迁移已分别提交。旧 `nx_*` import 通过模块 alias 保留，因此原 monkey-patch 和测试 patch 仍作用于真实实现；HTTP 路径保留。

S100 的 suite / architecture / Follow / route / object-voice 测试在隔离目录共 105 项通过。扩展专项测试发现 7 个旧 fixture 失败，在迁移前源码复现一致结果后，对齐当前 semantic API；没有恢复已淘汰的录像寻物 API。

## Phase 7

- 110 项静态及专项测试通过。
- 独立 ROS domain 187 的租约、停止、手动接管、底盘心跳过期测试通过，未启动 driver。
- S100 上 `luka_capabilities`、`luka_motion_gateway`、`luka_behaviors`、`luka_mission` 四包 colcon 构建通过。
- Nav2 smoother → `motion/nav`；旧/官方直接 Follow → `motion/follow`；Relocalization → `motion/relocalize`；可选 Recovery → `motion/recovery`。Heading Guard 输入 `motion/autonomy`，后续仍为 `/nx/nav_guarded` → Collision Monitor → `/nx/nav_safe` → Base。
- 官方 Follow 的 Nav2 action 通过 Behavior proxy 明确切换 Nav2 租约；未修改官方 C++ 算法。目标丢失、身份/深度/TF 门继续由原 target gate 控制。
- 租约需要 source、owner、gateway boot 与 generation；状态/lease 超时、显式停止和人工接管归零，禁止旧 generation 恢复运动。

### 架空轮实测

用户确认车轮架空且现场可停机后执行。首次底盘检查发现 2 号编码器 `bad free-protocol position frame`，网关拒绝许可，四轮目标 RPM 为 0；现场恢复后四轮有效反馈年龄约 5–84 ms。

初始化沿用匹配当前地图签名的已存位置，通过现有 ScanMapMatcher / covariance / map-scope policy：238 个有效端点、中位误差 0.05 m、15 cm 内比例 0.803、朝向候选唯一。

`live_navigation_wheels.py --wheels-off-ground` 使用真实 NavigateBehavior/Nav2 action 与 Safety/Base，速度上限 0.08 m/s，最长观察 2 s 后取消：action 已接受，编码器由 `[0,0,0,0]` 变为 `[1.7,5.7,-15.4,-12.0]` 度，收到 7 个安全速度样本，取消后四轮目标 RPM 确认为 0。编码器变化是架空轮证据，不能当作落地行驶距离。

### 远端状态保护

远端原 Git HEAD 为 `d660b12`，存在未提交的 Follow relock、bridge、C++、Base 和运行状态修改；没有覆盖它们。迁移前源码/参数及 local diff 保存在 `/home/sunrise/luka_architecture_rollback_20261007`，归档与 patch 的 SHA256 校验通过。

候选运行用独立临时 systemd unit，源和配置未覆盖生产工作区；传感器与 AMCL 使用原服务。正式生产部署必须合并远端用户改动并重新构建，不能用候选代码覆盖这些产品策略。

## 尚不能称为通过的项目

完整工作区构建、真实人物 Follow、重定位运动、真实手柄、落地受控导航、Phase 8 二次实测，以及最终部署/源码依赖扫描尚待后续记录。架空轮、ROS transport、静态/单元、colcon 和完整产品验收分别记录，不能互相替代。
