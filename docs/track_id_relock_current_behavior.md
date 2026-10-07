# Track ID 重锁现状

## 扫描结论

`/home/sunrise/luka_ws/perception` 的人体监视接口生成临时 `track_id`，Python bridge 从 `/api/people/follow-state` 读取已选目标，再发布 `/luka/selected_seg_targets`。YOLO26-Seg 只提供当前帧的人体实例与深度；CPU OSNet/ReID 已关闭，因此 `track_id` 不是永久身份。

原 bridge 在 `bridge.py` 的轮询路径中把 `stale_frame`、深度无效、源超时和目标缺失直接映射为 `self.desired = False`；并且通过 `last_id` 检查 ID 变化，在非单人自动选择时产生 `track_id_changed`。短暂漏帧或 tracker 重建 ID 会因此取消 `/official/enable_follow` 和 `/nx/follow_enable`。

官方 C++ 节点本身已有 `TRACKING`/`LOST` 状态和按位置的恢复逻辑，但它收到空目标或禁用服务后会取消 Nav2 goal 并发布 `FollowStatus DISABLED`。因此 bridge 的撤防是当前停跟的直接调用链：

```text
stale_frame / ID 变化
  -> bridge desired=false
  -> official enable_follow(false)
  -> Canceling all nav goals
  -> FollowStatus DISABLED
```

## 本次目标

保留显式服务关闭和真正 TF/监视器故障的安全撤防；将短暂感知异常与临时 ID 变化改为 GRACE/RELOCK/LOST，单人时以时间、空间和深度连续性接受新 ID。
