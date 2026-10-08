# 架构迁移阶段记录

执行日期：2026-10-07。Git 目标为 `TerryHank/luka_ws` 的 `main`。本地源目录 `D:/Workspace/luka_ws`；分阶段 S100 候选目录为 `/home/sunrise/luka_architecture_validation_20261007`，完整源码候选目录为 `/home/sunrise/luka_architecture_final_20261007`。两个目录均与原生产工作树隔离。

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

## Phase 8

Base Gate 改为持有 driver 实例，门控替换 driver 的导航/手动输入订阅与命令 timer，反馈 hook 继续更新编码器 freshness；nx_manual_base.py 保留旧命令入口，未拆成两个运行节点。Driver 电机协议未改。

6 包（包含既有 ddsm_car_control 和新 luka_base_gate）在隔离目录构建通过。架空轮检查发现 watchdog 回调同步等待服务会阻塞自己的 ROS 回调组，改为非阻塞取消并增加专项回归；提取出的 watchdog 缺失 String import 也已修复，并用 pyflakes 检查新包的名称作用域。

第二次架空轮 Nav2/Behavior → Gateway → Safety → composition Base Gate → driver 实测：action 已接受，编码器 [11.5,-11.3,-29.7,-51.4] → [12.9,-31.8,-11.4,-58.5] 度，8 个安全速度样本，停止确认通过。测试用 driver 临时参数上限为线速度 0.08 m/s、角速度 0.12 rad/s；生产参数文件未修改。Nav2 SpeedLimit 不替代最终全向速度上限，测试检查实际 driver 输出。

## Phase 9–11

- 新增 `luka_bringup` 分层 launch 与总入口，保留原导航 shell/launch wrapper。安装后的 `robot.launch.py --show-args` 检查通过；启动顺序不替代实际 readiness 门。
- 212 个历史源码/参数备份归入 `common/legacy/snapshots`，7 张旧图片归入 evaluator fixtures、3 份结果归入 artifacts。222 项路径、Git mode 与 SHA256 记录在 LEGACY_MOVES.tsv，并逐项校验；历史目录有 COLCON_IGNORE。运行配置与资源没有被当历史快照移走。
- 架构 CI 已发布到 `.github/workflows/architecture.yml`。GitHub run `37626968998`（`cc5c360`）通过。Capability、Mission、Behavior、Motion/Safety、Vehicle 层边界，以及 canonical 根目录、旧文件校验均受检查约束。
- 直接使用 driver 的 commissioning 工具也归入 Base Gate 边界，保留旧 console 命令入口。官方 Follow C++ 算法、target gate、感知 worker 没有因本轮重构而修改。

## 完整构建与回归

完整源码归档基于 `ebf8a8d`，SHA256 为 `bcbd3b9459a4906cd9f175d4c3de3063a7a1d4093d397b0f072b2ce371928626`，后续通过增量源码更新对齐修复提交。`colcon list` 发现 23 个唯一包名，完整 `colcon build` **23 包通过**。构建需要机器人既有 Orbbec ARM64 SDK 的 include/lib；已复制到候选目录，未上传二进制或构建输出。

S100 最终的 suite / architecture / Follow / route / object-voice 回归 **144 项通过**；Windows 主机侧 CI 范围 **97 项及 38 subtests 通过**。独立 ROS domain 187 的真实 transport 与 Follow→模拟 Nav2 action proxy **2 项通过**。后端是模拟 action server，不能当作人物跟随实测。

最终两包增量重建通过。源码扫描已排除根目录 build/install/log，避免复制式安装把同一 driver 算成跨层引用，并有对应 fixture 回归。`ebf8a8d` 归档之后的 13 个增量文件逐项 SHA256 对齐 `cc5c360`（文本仅归一化 CRLF）；候选 Base/Gateway 的已安装代码与源码逐字节对齐（同样归一化行尾），无差异。

完整 `colcon test` 跑完 23 包，汇总 **363 项报告测试、114 项报告失败、0 errors、10 skipped**。这些报告数包含 CTest 汇总与 xunit 子测试，不能视为 363 个独立业务用例。失败包为 `ai_msgs`、`ddsm_car_control`、`explore_lite`、`tros_person_following`；除 lint/格式/XML 项外，driver 有 35 个配置、路径和数值预期失败，不能全部归为 lint。

driver 的 106 个 canonical 文件与 `877992f` 基线比对无变化；在独立基线目录重跑得到 **35 failed / 213 passed**，与候选的 35 个失败名称一致，新增失败名称为 0。本轮没有扩展范围修复这些既有失败，因此全量测试仍不通过。完整结果保存在 [colcon-test-result.txt](../../evaluator/artifacts/architecture_20261007/colcon-test-result.txt)，结构化摘要见 [result.json](../../evaluator/artifacts/architecture_20261007/result.json)。

## 停机收尾

结束架空轮运行前，实际 `/ddsm/data_chain` 四轮目标 RPM 为 `[0,0,0,0]`。已停止本轮候选 Base/Nav2 临时服务，以及本轮启动的原传感器、定位服务；没有启用生产 agent 或自动运动入口。

停止服务发现 ROS SIGTERM 关闭上下文时 `executor.spin()` 抛出 context-invalid RuntimeError。Base 与 Motion Gateway 已补齐正常上下文关闭处理；活动上下文中的运行错误仍抛出。Gateway 在上下文关闭后只撤销内存租约，不向失效 publisher 发布。8 项无硬件停机回归通过；driver 原有三轮 stop_motor 与串口关闭逻辑保留。

另在 ROS domain 188 运行空闲停机检查，没有导航目标或速度输入：四轮 RPM 为 `[0,0,0,0]`，Gateway 的 active_source / owner 均为 null，两服务停机 Result=success / ExecMainStatus=0。原 TF listener 的后台线程仍可能在 SIGTERM 上报告 ExternalShutdownException，以及 ROS logging 的失效上下文提示；没有扩大本轮范围改写 tf2 实现或电机 driver，进程正常退出且停止确认成立。

## 尚不能称为通过的项目

真实人物 Follow、重定位运动、真实手柄、落地受控导航及正式生产切换尚未通过；落地测试按用户最新要求暂缓。未把临时候选替换为原 `/home/sunrise/luka_ws`，因为其中有应保留的未提交产品改动。架空轮、ROS transport、静态/单元、colcon 和完整产品验收分别记录，不能互相替代。
