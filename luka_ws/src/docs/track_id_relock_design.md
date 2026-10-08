# Track ID 重锁设计

follow 请求与 tracker 轨迹号解耦。`follow_enabled` 只由用户服务或真正安全故障改变；`target_track_id` 只代表当前帧的临时轨迹号。

bridge 状态为 `IDLE -> TRACKING -> GRACE -> RELOCK -> TRACKING/LOST`。短暂的 `stale_frame`、源超时、深度异常和目标缺失不再关闭 follow；GRACE/RELOCK/LOST 发布空目标，使官方节点和底盘保持停止，直到目标重新确认。

单人自动重锁需要：

- 时间间隔不超过 1.5 秒；
- 三维位置变化不超过 0.8 米；
- 深度变化不超过 0.6 米。

所有阈值通过 ROS 参数声明。多人模式不随机接受任意新轨迹，仍依赖页面选择和已有官方节点的候选处理。
