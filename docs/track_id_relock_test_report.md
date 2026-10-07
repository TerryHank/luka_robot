# Track ID 重锁测试报告

## 静态检查

- bridge 已删除 `track_id_changed -> desired=false` 的撤防路径。
- 单人模式会在短暂异常期间保留 follow 请求，并允许临时轨迹号变化。
- `stale_frame`、源超时、深度异常和目标缺失进入 GRACE/RELOCK/LOST。
- TF 不可用和 monitor 不可用仍属于安全撤防条件。

## 已执行验证

1. Python bridge 通过 `py_compile`。
2. 计划阈值已参数化：`id_grace_timeout=0.8`、`relock_max_time_gap=1.5`、`relock_max_position_delta=0.8`、`relock_max_depth_delta=0.6`、`target_lost_timeout=3.0`。
3. 目标板已编译并加载 `target_relock.yaml`；在人体 worker 有目标时连续 20 秒回读得到 144/144 条 `enabled_requested=true`、0 条撤防，状态均为 `TRACKING`。
4. 30→33→39 的几何连续性单元测试已通过。当前尚未在真实相机画面中强制制造 ID 切换；需要人在画面内并出现 tracker 重建才能完成该项实车观测。

## 限制

本次不启用 OSNet/ReID，不改变 YOLO26-Seg、RGB-D 深度算法、底盘驱动或 Nav2。单人模式的连续性判定依赖当前有效深度和相机时间戳；多人模式仍需要明确的页面目标选择。
