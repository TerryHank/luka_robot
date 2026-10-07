# 历史文件与测试资料分类

本轮仅移动已跟踪、且 canonical 可执行源码没有引用的历史副本，没有删除包实现或运行数据。

- 212 个 .before / .pre_ / .bak / backup-* 历史源码和配置副本移到 common/legacy/snapshots，按原相对路径保留。每文件移动前后 SHA256 一致。
- 7 张历史测试图片移到 evaluator/fixtures/legacy_images；3 个历史测试结果 JSON 移到 evaluator/artifacts/legacy_results。历史结果中记录的原始现场路径不改写，通过 LEGACY_MOVES.tsv 对照到归档位置。
- common/legacy/COLCON_IGNORE 防止历史包参与 ROS 构建；不会禁止显式运行已有 common/legacy/s100_object_api.py 产品兼容入口。
- .vscode/browse.vc.db、db-shm、db-wal、db.lock 为编辑器缓存，保留本地文件并从 Git 当前树取消跟踪；历史提交保留。VS Code 的配置 JSON 仍跟踪。
- 活跃地图资源、模型、当前配置/状态、API 实现、系统脚本及 src/system/runtime 兼容 symlink 未在此阶段移动。上游已移走的独立 Orbbec SDK 不恢复。

文件级恢复表见 [LEGACY_MOVES.tsv](LEGACY_MOVES.tsv)，已检查的活跃引用保留表见 [LEGACY_REFERENCED.tsv](LEGACY_REFERENCED.tsv)。恢复历史实验应使用原位置或备份标签，不将历史副本加入当前运行路径。
