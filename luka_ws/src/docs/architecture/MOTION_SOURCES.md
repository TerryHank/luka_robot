# 运动源清单（源码基线）

这是 `17a60d4` 的 source/config inventory，已与上游 `877992f` 的路径迁移复核；未观察 S100 的运行进程或发布者。Phase 0 保持所有 topic 和开关不变。

## 当前主链与额外入口

| 源 | 入口 / topic | 下游 | 启用依据与迁移要求 |
|---|---|---|---|
| Nav2 controller / behavior | `/nx/nav_raw` | velocity smoother → `/nx/nav_smoothed` → Heading Guard → `/nx/nav_guarded` → Collision Monitor → `/nx/nav_safe` → Base | `system/bringup/nx_navigation.launch.py`；Phase 7 改 smoother 输出到 `motion/nav` |
| 官方 tros_person_following | `/nx/nav_smoothed` 或 `/navigate_to_pose` | direct 经 Heading Guard/Collision Monitor；action 经 Nav2 | `selected_follow.launch.py`，默认 dry-run；direct 改 `motion/follow`，保留目标门与官方算法 |
| 旧 `FollowController` | `/nx/follow_safe` | `nx_manual_base.on_follow_cmd_vel` | `nx_dashboard.init` 构建，跟随 gate 与 fail-closed；**绕过共享 Heading Guard/Collision Monitor**，不能从 Phase 7 清单遗漏 |
| `Relocalization` rotate_scan | `/nx/nav_guarded` | Collision Monitor → Base | `nx_relocalization.py`，绕过 Heading Guard；Phase 7 改 `motion/relocalize` |
| 可选 `EscapeRecovery` | `/nx/web_teleop_cmd_vel` | Base 网页手动安全路径 | `LUKA_SOFTWARE_ONLY=1` 时构建，`NX_SAFE_ESCAPE=1` 才启用；它是自主源，须迁至 `motion/recovery` |
| `WebTeleop` 人工源 | `/nx/web_teleop_cmd_vel` | Base 人工 lease / obstacle / watchdog | 保留人工接管，不能错误地迁成自主租约 |
| Joystick | `/joy`，Base 的人工 callback | Base 仲裁与测量反馈 | 保留手柄接管与 navigation/follow 互斥 |

同一 topic 名称不能证明有单一所有者，特别是官方 Follow/Nav2 共用 `/nx/nav_smoothed`，Recovery/网页手动共用 `/nx/web_teleop_cmd_vel`。现场 unique publisher 和有效 enable 状态留待集成验收。

## 旧工具与 driver 包内行为

| 文件 | 源码入口 | 审计结论 |
|---|---|---|
| `visualization/console/person_follow_node.py` | `/cmd_vel_nav` | 旧 Follow 实现；不是本轮官方 selected Follow 的替代品 |
| `visualization/console/person_follow_demo.py` | `args.cmd_topic`，默认 `/cmd_vel_nav` | 独立 demo，存在显式 `--drive`；本轮不启动 |
| `visualization/console/mecanum_dance_demo.py` | `topic`，默认 `/cmd_vel_nav` | 独立 demo；本轮不启动 |
| `control/ddsm_car_control/.../ddsm_auto_localizer.py` | 参数 `cmd_vel_topic` 默认 `/cmd_vel_nav` | 额外重定位实现，未证明现场活跃 |
| `.../ddsm_mission_control.py`、`final_approach_navigator.py` | 参数 `cmd_vel_topic` 默认 `/cmd_vel_nav` | driver 包内仍有产品/行为职责，未来需评审启动配置 |
| `.../elevator_entry_controller.py` | `/cmd_vel` 与 Nav2 action | 独立升降梯行为；不能视作已纳入统一安全链 |
| 官方 `tros_person_following` C++ | `cmd_vel_topic` 默认 `/cmd_vel` | 产品 launch 显式覆盖为 dry-run 或 `/nx/nav_smoothed`；不修改上游算法 |
| `teleop_twist_keyboard`、driver `gamepad_teleop` | 配置 topic，默认 `cmd_vel` / `/cmd_vel` | 人工工具；运行配置需现场核实 |

这份清单区分产品主入口、备用自主入口与人工工具，未将未启动工具当作运行证据。后续总启动入口必须明确哪些启用、哪些禁止并发。

## Phase 7 新门控要求

每个自主源须显式申请租约，同一时刻只有一个有效 source。租约/命令超时输出零；人工接管、停止、generation/epoch 变化撤销旧授权。Source identity、lease age、command age、blocked reason 和 generation 必须可诊断。Nav2/Follow 互斥、旧目标取消确认、目标丢失停车和 Base encoder/scan/TF freshness 不得弱化。

`/nx/nav_safe` 仍通向 Base Gate，再到 DDSM；不能绕过 Base。Phase 7 的真实 topic 改动只能在 Phase 0–6 测试通过后实施；本轮只冻结与记录现状。
