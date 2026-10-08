# 官方人体跟随策略对齐结果

日期：2026-10-08。机器人工作区：`/home/sunrise/luka_ws`。
上游基线：D-Robotics/tros_person_following `202e8c8a04dc41e3d3771daa131b852cc24f7c0d`。

## 已完成

- 恢复官方 IDLE 观察与超时旋转找人。
- 恢复 TRACKING 近距离边缘转向。
- 恢复 LOST 观测点导航、定向扫描、扫描完成后的轮次推进、超时/失败结束与重锁打断。
- 恢复官方距离带 withhold：不发送新目标、不取消已有目标；过近取消。
- 移动目标可在到达前更新 NavigateToPose，保留导航栈的目标转换行为。
- 显式对齐官方策略参数及默认单人 MOT 变号桥接，重锁距离为 1/2/3 m；加入 UPSTREAM.json 契约测试防止回落到 C++ 默认值。
- 对齐盲区使能话题；蜂鸣策略恢复官方节流配置。平台实际消费者联动未在本轮验收。

## 沿用的本机适配

- Orbbec 注册 RGB-D、当前定位/SLAM、Nav2、速度平滑、航向约束、碰撞监测及底盘许可链保留。
- 旋转通过已有 Nav2 Spin Action；跟随核心不发布 Twist，不新建速度出口。
- NavigateToPose 与 Spin 互斥，等待自有任务终止；旋转前及旋转退出后的导航放行还确认轮式里程计停稳。
- 停稳门：里程计新鲜且有限、child frame 正确、至少2份不同时间戳样本、持续至少0.1秒低于0.02 m/s与0.05 rad/s。
- 取消只操作自有 UUID/句柄，generation 隔离迟到接受/结果；不把拒绝或失败扫描当作成功。
- dry_run 发布导航与旋转候选，不能模拟成实际到达或实际扫描完成。
- 默认 `dry_run`、跟随关闭；本轮没有启动生产跟随或实车运动目标。

官方直接 Twist 的运动执行方式被适配为本机安全 Action 执行方式。因此策略流程已对齐，不能称二进制原版或动作时序已经实车等价。
实际旋转速度由当前 Nav2/底盘限制决定，未用官方兼容速度参数覆盖现有导航配置。
上游当前观测点选择可能再次选择同一 LKP；没有额外声称不同轮次必然选不同位置。

## 验证证据

| 项目 | 结果 |
| --- | --- |
| 两个受影响包构建 | 通过：tros_person_following、s100_person_following_integration |
| 新增官方行为与安全模拟 | 20 项通过 |
| 集成包完整注册回归 | 52 tests，0 errors / failures / skipped；包含46项实际测试及6项CTest汇总，不按52个独立功能计算 |
| 既有 SLAM/Nav2/底盘保护文件 | 6个文件SHA-256一致 |
| 工作区结构与包唯一性 | 通过；当前24个唯一包名、12个功能所有者 |

所有模拟使用隔离 ROS domain、合成 TF/感知/里程计及模拟 NavigateToPose/Spin 服务器，没有电机速度发布。
模拟器的接受回复先于控制循环、到达TF先于成功结果，以匹配真实导航反馈顺序。

未替换地图，未重启SLAM/Nav2，未推送Git或修改其他任务的OELLM工作。
尚未进行真人遮挡/交叉、旋转保持目标视野、8秒搜索预算内实际轮次、近障安全和实测最终停稳验收。

## 代码与证据路径

- `src/control/tros_person_following/src/person_following_node.cpp`
- `src/control/tros_person_following/include/tros_person_following/person_following_node.h`
- `src/control/s100_person_following_integration/config/person_following_s100.yaml`
- `src/control/s100_person_following_integration/config/UPSTREAM.json`
- `src/control/s100_person_following_integration/test/test_official_behavior_ros.py`
- `src/control/s100_person_following_integration/test/test_strategy_contract.py`
- `log/official_follow_alignment_focused.xml`
- `log/official_follow_alignment_colcon_test.log`
- `build/s100_person_following_integration/Testing/Temporary/LastTest.log`

迁移前源码小快照：`~/luka_archives/person-follow-alignment-20261008/before.tar.gz`，106067字节；本机也保留一份。包含源码/配置/测试，不包含模型、虚拟环境或构建文件。

## 后续现场入口

仍使用 `src/system/scripts/start_official_person_following.sh`。
预检现在要求 NavigateToPose、Spin及唯一wheel/odom发布者；进入 `nav2_action` 仍须先验收现场输入，再显式设置 `input_contract_verified=true`。
本轮未把模拟成功当作该现场确认。
