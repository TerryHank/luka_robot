# 四路超声波导航接入

已部署：nx-sonar-monitor 采集 → nx-sonar-ros → /sonar/nav/* → local_costmap 的 sonar_layer（RangeSensorLayer）→ 原有 inflation_layer。

- 原始话题 /sonar/{front_left,front_right,left,right} 保留真实距离，最大量程暂按 5 m。
- 导航专用话题 /sonar/nav/*：有效距离 ≤0.8 m 用于标记；>0.8 m 转为导航层最大读数 0.8001 m，仅清除该层旧障碍，不清除激光雷达层。
- 任一路无有效回波或超过 0.8 秒不更新，暂停全部导航专用话题；Range 层无读数 1.5 秒后不再视为当前有效数据。故障恢复后需检查规划状态；必要时在停车状态重启导航。
- 60 度声束为标称初值，不代表实测角度或精确障碍轮廓。
- 实物位置沿用用户测量；高度按现有底盘 ground-plane 模型表达。车身 footprint 保留既有设置，未缩小。
- 超声波已影响导航局部规划，不影响手柄速度；独立末端速度保护仍为试算。
- 没有新增自动出发、掉线后重发旧目标或运动测试。

## 验证

隔离 ROS Domain 88 中原生插件试验：50 cm 回波产生致命障碍格；最大范围清除后超声波格消失；同位置独立激光层障碍保留。真实 Domain 87 核实插件已启用、四路 Range 持续发布和局部地图输出。

当前阻碍实车验证：map→base_link 定位未初始化。需要用户核对地图定位后，再做低速障碍绕行测试。手柄不具备本轮新增的超声波自动制动。

回退：停车后将 config/nx_nav2.yaml.before-sonar-layer 恢复为 config/nx_nav2.yaml，再重启 nx-navigation。仅停止数据桥会使已启用的 Range 层超时，不能替代回退。
