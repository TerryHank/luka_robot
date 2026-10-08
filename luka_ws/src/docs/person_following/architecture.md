# 实际架构

```mermaid
flowchart TD
  subgraph Existing["已有系统，复用"]
    A["Astra Pro Plus RGB-D，640x480"]
    T["已有定位和标定 TF"]
    C["已有 Nav2 Costmap"]
    N["已有 NavigateToPose"]
    B["已有运动安全链与底盘"]
  end
  subgraph Added["最小接口适配"]
    R["RGB 转 NV12，尺寸和时间戳不变"]
    Q["配准深度与分割配对，时间差不超过 40ms"]
  end
  subgraph Official["官方实现"]
    S["S100 YOLOv8-Seg"]
    F["官方深度融合，独立调试栅格"]
    M["官方 MOT 与 ID 分配"]
    P["官方 IDLE TRACKING LOST 和目标决策"]
  end
  D["dry_run 候选目标和诊断"]
  A --> R
  R --> S
  A --> Q
  S --> Q
  Q --> F
  F --> M
  M --> P
  T --> P
  C --> P
  P -->|dry_run| D
  P -->|显式 nav2_action| N
  N --> B
```

新 Launch 不启动相机、StereoNet、SLAM、定位、TF、Costmap、Planner、Controller、底盘、WebSocket 或 Foxglove。
启动前通过新建 ROS 图查询器检查需要创建的发布者和跟随节点，避免重复实例。

官方动态选人、运动条件、距离带、迟滞、死区、限频、空闲栅格、预测和 MOT 重锁保留。
原 IDLE 搜索改为静止观察，edge-turn 禁用；LOST 保留预测/导航到观察点，到达后等待重锁或超时。
不执行方向旋转扫描，不伪造旋转完成。该限制与完整上游旋转搜索能力有区别。

核心不创建任何 Twist publisher。dry_run 在原 Action 发送决策点输出候选，不发送或取消任何 Action。
nav2_action 只发送 NavigateToPose，按自身 handle/UUID 取消；generation 过滤迟到反馈/结果，关闭跟随后迟到接受的目标按自身 UUID 取消。
独立可执行文件在 SIGINT/SIGTERM 时保留 ROS 客户端 3 秒，处理迟到响应与取消；组件插件仍保留，但完整优雅关闭测试使用独立入口。
SIGKILL 或响应超过关闭等待时间无法保证取消，须由已有运动安全链和操作员处理。

MOT 的 track_id 是临时轨迹编号，不具备 ReID 永久身份保证。本链路不调用旧 HTTP 选人、ReID、EdgeTAM 或额外运动控制器。
