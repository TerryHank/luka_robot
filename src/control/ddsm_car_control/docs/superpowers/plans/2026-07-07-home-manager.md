# Home Manager 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 在现有 DDSM ROS2/Nav2 系统里增加一个可由 Foxglove 触发的回 Home 功能。

**架构：** 新增 `ddsm_home_manager` 节点，保存/读取 `map` 坐标系下的 Home 位姿，通过 Nav2 `NavigateToPose` action 发起回 Home。节点随 `ddsm_bringup.launch.py mode:=nav/slam_nav` 启动，但不会自动让车运动。

**技术栈：** ROS 2 Jazzy、rclpy、tf2_ros、nav2_msgs/action/NavigateToPose、std_msgs。

---

### 任务 1：打包与接口测试

**文件：**
- 创建：`src/ddsm_car_control/test/test_home_manager_packaging.py`
- 修改：`src/ddsm_car_control/setup.py`
- 修改：`src/ddsm_car_control/launch/ddsm_bringup.launch.py`
- 创建：`src/ddsm_car_control/config/home_pose.yaml`

- [ ] **步骤 1：编写失败的测试**

测试要求：
- `setup.py` 安装 `ddsm_home_manager = ddsm_car_control.ddsm_home_manager:main`
- `ddsm_bringup.launch.py` 暴露 `enable_home_manager`、`home_pose_file`、`home_map_file`
- launch 中存在 `executable="ddsm_home_manager"`，并只在导航相关模式启用
- 默认配置文件有 `frame_id: map`、`x/y/yaw` 字段

- [ ] **步骤 2：运行测试验证失败**

运行：`python3 -m pytest src/ddsm_car_control/test/test_home_manager_packaging.py -q`
预期：FAIL，缺少测试文件对应的生产实现。

- [ ] **步骤 3：实现最少打包代码**

添加 console script、launch Node、默认 YAML。

- [ ] **步骤 4：运行测试验证通过**

运行：`python3 -m pytest src/ddsm_car_control/test/test_home_manager_packaging.py -q`
预期：PASS。

### 任务 2：Home 配置和命令逻辑

**文件：**
- 创建：`src/ddsm_car_control/ddsm_car_control/ddsm_home_manager.py`
- 创建：`src/ddsm_car_control/test/test_home_manager.py`

- [ ] **步骤 1：编写失败的测试**

测试纯函数：
- `load_home_pose()` 能读取 YAML 并输出 map 位姿
- `dump_home_pose()` 能保存 Home 点和地图路径/hash
- `map_identity_matches()` 能在地图不一致时拒绝回 Home
- `make_navigate_goal()` 生成 `NavigateToPose.Goal`

- [ ] **步骤 2：运行测试验证失败**

运行：`python3 -m pytest src/ddsm_car_control/test/test_home_manager.py -q`
预期：FAIL，模块不存在。

- [ ] **步骤 3：实现最少节点代码**

节点订阅：
- `/home/set_current` (`std_msgs/Empty`)
- `/home/go` (`std_msgs/Empty`)
- `/home/cancel` (`std_msgs/Empty`)

节点发布：
- `/home/status` (`std_msgs/String`)
- `/home/pose` (`geometry_msgs/PoseStamped`)

节点行为：
- set_current 时查 `map -> base_link`，保存当前位姿
- go 时校验 Home 文件和地图 identity，通过 Nav2 action 导航
- cancel 时取消当前 action goal

- [ ] **步骤 4：运行测试验证通过**

运行：`python3 -m pytest src/ddsm_car_control/test/test_home_manager.py -q`
预期：PASS。

### 任务 3：构建与集成验证

**文件：**
- 修改：安装空间由 `colcon build --symlink-install --packages-select ddsm_car_control` 生成

- [ ] **步骤 1：构建**

运行：`source /opt/ros/jazzy/setup.bash && colcon build --symlink-install --packages-select ddsm_car_control`
预期：构建成功。

- [ ] **步骤 2：全量包测试**

运行：`source /opt/ros/jazzy/setup.bash && source install/setup.bash && python3 -m pytest src/ddsm_car_control/test -q`
预期：全部测试通过。

- [ ] **步骤 3：启动命令检查**

运行：`source /opt/ros/jazzy/setup.bash && source install/setup.bash && ros2 pkg executables ddsm_car_control | grep ddsm_home_manager`
预期：能看到 `ddsm_home_manager`。
