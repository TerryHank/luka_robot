# 层级规则与 Phase 0 例外

| 层 | 允许 | 禁止 |
|---|---|---|
| Interaction | UI、语音、HTTP assistant API、状态 | ROS 速度、Nav2 goal、DDSM/RS485 |
| Capability | 工具目录、grounding、校验、policy、dispatch | 电机协议、raw autonomous Twist |
| Mission | 任务状态、语义/物体记忆、Behavior 调用 | Twist、Nav2 ActionClient、电机/串口 |
| Behavior | Nav2 adapter、官方 Follow、Gateway client | DDSM/电机串口 |
| Motion Safety | 租约/仲裁/watchdog、安全限制与停止 | 规划、人体身份、任务决策、电机协议 |
| Base/Vehicle | 最终许可、人工接管、电机协议、编码器 | 语义任务、LLM 工具逻辑 |

## 已执行检查

`evaluator/architecture` 用 AST 检查实际 import、调用和 topic 字符串。注释和 docstring 中描述“禁止 Twist/Nav2”不算调用；不得以删安全说明的方式让检查变绿。

- **Interaction：**递归检查 `system/xiaozhi` 无 `geometry_msgs`、`Twist(`、`NavigateToPose`、`ddsm_car_control`、`/cmd_vel`，且 client 保留 Assistant API。
- **Mission：**检查当前 `nx_patrol_mission.py` 与后续 `mission/` 无电机/串口/Twist/Nav2 实现；保留 Patrol callback 和状态恢复入口。
- **Vehicle：**检查所有 canonical Python source 的显式 DDSM import。`control/ddsm_car_control` 和未来 `vehicle/` 是实现边界；边界外只允许下表的原有精确 import 集合。
- **Motion：**冻结 console 的七个直接 Twist source（包括三个旧/demo 工具），检查 Nav2 remap、官方 Follow dry-run 与真实 topic、Heading Guard、两份 Collision Monitor 配置和 Base 输入。新增或改动 source 必须先更新评审清单与相应安全验证。

测试读取源码，不导入节点。driver 导入检查覆盖别名；publisher 检查覆盖 Twist 别名和关键字参数。它们不能证明动态 import、动态字符串 topic、C++ 全部节点、ROS remap 后的图、参数覆盖或唯一发布者：这些需要后续集成验证。C++ 官方 Follow 的入口目前由 launch 合同检查覆盖。

## 原有 Vehicle import 例外

| canonical 文件 | 冻结 import | 用途 / 后续处理 |
|---|---|---|
| `visualization/console/nx_manual_base.py` | `ddsm_car_control.zdt_mecanum_rs485_bridge` | 现有底盘门与 driver 继承；Phase 8 组合迁移 |
| `visualization/console/nx_manual_stop.py` | `ddsm_car_control.zdt_y42_protocol` | 调试/急停电机工具，import 会打开串口；保留但不执行 |
| `visualization/console/nx_readonly_odom.py` | `ddsm_car_control.zdt_y42_protocol`、`ddsm_car_control.zdt_mecanum_kinematics` | 只读编码器调试；不作为自主行为依赖 |

`nav_llm_agent` 和 Dashboard 现存的 Nav2 action 所有权、旧 Follow/recovery bypass 在 [当前图](CURRENT_RUNTIME_ARCHITECTURE.md) 中明确记录，Phase 0 不宣称它们已经满足目标分层。后续阶段才逐项迁移，不通过新增大范围 allowlist 掩盖问题。

## 扫描范围

兼容 symlink 不重复审计；canonical 目标须独立被扫描。`src/`、测试、legacy/history/fixture/artifact 目录、`backup-*` 与 `.before*` / `.pre_*` / `.bak*` 历史文件不当作当前运行实现。Phase 10 对它们分类前先查引用，不能因此推断它们已可删除。未来把活跃源放进排除目录属于违反目录用途，需要评审。

未来 `mission/` 目前不存在，测试同时覆盖现存 Patrol，但不代表 Mission package 已建立。正式 Capability、Behavior 和 Motion Gateway 边界及 CI 在后续 Phase 加入。
