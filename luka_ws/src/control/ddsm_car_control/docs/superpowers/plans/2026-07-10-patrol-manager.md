# 多点导航与自主巡航实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 新增 `ddsm_patrol_manager`，让当前 `auto_nav` 导航栈支持 Foxglove 控制的多点导航、循环巡航，并在送餐点调用现有 final approach 精靠。

**架构：** `ddsm_patrol_manager` 作为业务层节点启动后保持空闲，接收 `/patrol/*` 控制话题，读取或维护路线 YAML。普通点逐点调用 Nav2 `NavigateToPose` action；`delivery_stop` 或 `final_approach: true` 点发布 `/goal_pose`，等待 `/final_approach/status=final_reached` 后再进入下一点。

**技术栈：** ROS 2 Jazzy、rclpy、Nav2 `NavigateToPose`、`geometry_msgs/PoseStamped`、`nav_msgs/Path`、`visualization_msgs/MarkerArray`、YAML。

---

### 任务 1：测试路线模型与 final approach 判定

**文件：**
- 创建：`/home/terry/ddsm_car_ws/src/ddsm_car_control/test/test_patrol_manager.py`

- [x] **步骤 1：编写失败的测试**

覆盖 `load_route`、`dump_route`、`append_pose_waypoint`、`PatrolCursor`、`classify_final_approach_status`、`make_route_markers`。

- [x] **步骤 2：运行测试验证失败**

运行：

```bash
colcon test --packages-select ddsm_car_control --pytest-args -q test/test_patrol_manager.py
```

预期：`ModuleNotFoundError: No module named 'ddsm_car_control.ddsm_patrol_manager'`。

### 任务 2：实现 patrol manager

**文件：**
- 创建：`/home/terry/ddsm_car_ws/src/ddsm_car_control/ddsm_car_control/ddsm_patrol_manager.py`

- [ ] **步骤 1：实现路线 YAML 模型**

实现 `Waypoint`、`PatrolRoute`、`load_route`、`dump_route`、`append_pose_waypoint`、`PatrolCursor`。

- [ ] **步骤 2：实现节点控制接口**

订阅 `/patrol/add_pose`、`/patrol/clear`、`/patrol/start_once`、`/patrol/start_loop`、`/patrol/pause`、`/patrol/resume`、`/patrol/stop`、`/patrol/load_route`、`/patrol/save_route`、`/patrol/go_home`。

- [ ] **步骤 3：实现普通点与精靠点执行**

普通点调用 `navigate_to_pose`；精靠点发布 `/goal_pose` 并等待 `/final_approach/status=final_reached`。

### 任务 3：打包和启动集成

**文件：**
- 修改：`/home/terry/ddsm_car_ws/src/ddsm_car_control/setup.py`
- 修改：`/home/terry/ddsm_car_ws/src/ddsm_car_control/package.xml`
- 修改：`/home/terry/ddsm_car_ws/src/ddsm_car_control/launch/ddsm_bringup.launch.py`
- 修改：`/home/terry/ddsm_car_ws/restart_nav_reset.sh`
- 创建：`/home/terry/ddsm_car_ws/src/ddsm_car_control/config/patrol_route.yaml`

- [ ] **步骤 1：添加 console script 与依赖**

安装 `ddsm_patrol_manager = ddsm_car_control.ddsm_patrol_manager:main`，新增 `visualization_msgs` 依赖。

- [ ] **步骤 2：加入统一 launch**

新增 `enable_patrol_manager`、`patrol_route_file`、`patrol_require_localization_ready`，在 `nav/auto_nav` 模式启动 patrol manager。

- [ ] **步骤 3：加入一键脚本参数**

脚本传入 `patrol_route_file`，停止旧节点时包含 `ddsm_patrol_manager`。

### 任务 4：验证

- [ ] **步骤 1：构建**

```bash
colcon build --symlink-install --packages-select ddsm_car_control
```

- [ ] **步骤 2：运行测试**

```bash
colcon test --packages-select ddsm_car_control
colcon test-result --verbose --test-result-base build/ddsm_car_control
```

- [ ] **步骤 3：非运动启动参数验证**

```bash
source /opt/ros/jazzy/setup.bash
source /home/terry/ddsm_car_ws/install/setup.bash
ros2 pkg executables ddsm_car_control | grep ddsm_patrol_manager
ros2 launch ddsm_car_control ddsm_bringup.launch.py --show-args | grep patrol
```
