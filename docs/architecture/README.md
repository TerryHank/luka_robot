# Luka 架构护栏

本目录记录手术重构计划 **Phase 0–11** 的实现与验收。参考仓库为 `TerryHank/luka_ws`，初始审计基线为 `17a60d4bf9c0ae367342339df198b44166d5a258`，审计日期为 2026-10-07。远端新增 `877992f` 的 canonical 路径迁移与 `84160de` 的 SDK 归档均已吸收，没有覆盖并发更新。

代码整合在 Windows 本地执行，完整构建、ROS 集成和两次架空轮验收在 S100 的隔离候选目录执行。完整产品验收尚未通过：落地导航、真实人物跟随和真实手柄按用户要求暂缓；原生产工作树的未提交改动保留，未切换正式生产目录。

- [当前依赖与计划差异](CURRENT_RUNTIME_ARCHITECTURE.md)
- [迁移前依赖快照](BASELINE_RUNTIME_ARCHITECTURE.md)
- [分阶段验收及未完成项](REFACTOR_ACCEPTANCE.md)
- [canonical 启动方式](BRINGUP.md)
- [历史文件归档及校验](REPOSITORY_HYGIENE.md)
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

## 执行进度

用户随后授权完整执行。Phase 1–11 的代码、兼容入口、启动、归档和 CI 已提交；后续验收范围与证据见 REFACTOR_ACCEPTANCE.md。上述 39 / 9 项属于 Phase 0 历史结果，不能代替当前测试结果。
