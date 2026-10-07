# Luka 架构护栏

本目录完成手术重构计划的 **Phase 0**：记录当前源码依赖，冻结已知运动入口，阻止新增跨层调用。参考仓库为 `TerryHank/luka_ws`，初始审计基线为 `17a60d4bf9c0ae367342339df198b44166d5a258`，审计日期为 2026-10-07。提交前远端新增 `877992f` 的 canonical 路径迁移，Phase 0 已 rebase 到该提交并重新验证，没有覆盖并发更新。

此次在 Windows 本地检出目录执行，未连接 S100。文中“当前”指基线源码和启动配置；不代表现场服务、参数、进程或 topic 发布者已经核实。

- [当前依赖与计划差异](CURRENT_RUNTIME_ARCHITECTURE.md)
- [目标架构与分阶段门槛](TARGET_RUNTIME_ARCHITECTURE.md)
- [层级规则和现存例外](LAYER_RULES.md)
- [完整运动源清单](MOTION_SOURCES.md)

## 检查

在仓库根目录运行（本机使用 `py`，Linux 使用 `python3`）：

```sh
python3 -m pytest evaluator/suite -q
python3 -m pytest evaluator/architecture -q
```

护栏解析源码，不 import ROS 节点，不连接串口，不发目标或速度。`src/`、`system/runtime/tools` 的 Linux symlink 均保留；上游 `877992f` 已移除根目录兼容链接，本轮沿用 `system/bringup` 等 canonical 入口。Windows 的普通 symlink blob 检出不能代替 Linux colcon 或启动验收。

## 基线问题及最小测试修复

首次执行既有 suite：32 项通过，2 个收集错误。

1. `evaluator/suite/test_target_gate.py` 的 `dict(class=...)` 是非法 Python。改为设置字典的 `class` 键，保留原输入和全部断言。
2. `test_llm_backends.py` 测试纯 fallback，却经 `llm/__init__.py` 加载 ROS factory，缺少生成的 `ai_msgs` 时无法收集。测试直接执行真实 `base.py` / `fallback.py` 的纯实现，未伪造 ROS 消息或修改产品导入。原无运动接口检查也排除 docstring：`base.py` 的说明文字明确写了禁止的 `cmd_vel`，不能把该说明当作运动调用。

修复后既有 suite：**39 项通过**。Architecture：**9 项通过**。这些是主机侧静态/单元测试结果；ROS 构建、板端推理和真机验收均未执行。没有修改产品源码、launch、参数、运动 topic 或兼容链接。

## 本轮停止点

按执行计划第 23 节，本轮完成 Phase 0 的审查、测试、commit 和 `push origin main` 后停止。后续 Phase 1–6 的能力/任务/行为迁移，以及 Phase 7 运动链改造，属于下一阶段。
