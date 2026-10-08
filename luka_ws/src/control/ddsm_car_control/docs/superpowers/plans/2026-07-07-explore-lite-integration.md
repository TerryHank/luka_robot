# Explore Lite 自动探索集成计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 将 ROS 2 `explore_lite` 源码包安装到 `/home/terry/ddsm_car_ws/src`，并在现有 `ddsm_car_control` 统一启动中加入 `mode:=explore`。

**架构：** `mode:=explore` 复用现有底盘、IMU、EKF、雷达、slam_toolbox 和 Nav2 启动链路，再额外 include `explore_lite` 的 `explore.launch.py`。自动探索不作为默认导航模式启动，只有显式选择 `mode:=explore` 时运行。

**技术栈：** ROS 2 Jazzy、Nav2、slam_toolbox、m-explore-ros2/explore_lite、ament_cmake、ament_python。

---

### 任务 1：测试驱动固定启动包装

**文件：**
- 修改：`/home/terry/ddsm_car_ws/src/ddsm_car_control/test/test_unified_launch_packaging.py`
- 修改：`/home/terry/ddsm_car_ws/src/ddsm_car_control/package.xml`
- 创建：`/home/terry/ddsm_car_ws/src/ddsm_car_control/config/explore_lite.yaml`
- 修改：`/home/terry/ddsm_car_ws/src/ddsm_car_control/launch/ddsm_bringup.launch.py`

- [ ] **步骤 1：编写失败的测试**

新增测试断言：
- `ddsm_bringup.launch.py` 包含 `"explore"` 模式
- `enable_explore` 参数存在
- `explore_params_file` 参数存在
- include `explore_lite/launch/explore.launch.py`
- `mode:=explore` 时 Nav2 使用官方 `slam:=True` 链路
- `package.xml` 声明 `explore_lite`

- [ ] **步骤 2：运行测试验证失败**

运行：
`source /opt/ros/jazzy/setup.bash && source install/setup.bash && python3 -m pytest src/ddsm_car_control/test/test_unified_launch_packaging.py::test_unified_launch_exposes_explore_mode -q`

预期：FAIL，缺少 `"explore"`。

- [ ] **步骤 3：最少实现**

新增 `enable_explore`、`explore_params_file`，将 `explore` 加入需要 SLAM+Nav2 的模式，并 include `explore_lite`。

- [ ] **步骤 4：运行测试验证通过**

运行同上，预期 PASS。

### 任务 2：源码安装与构建

**文件：**
- 创建目录：`/home/terry/ddsm_car_ws/src/explore_lite`

- [ ] **步骤 1：下载源码**

运行：
`git clone https://github.com/robo-friends/m-explore-ros2.git /home/terry/ddsm_car_ws/src/m-explore-ros2`

- [ ] **步骤 2：安装依赖**

运行：
`source /opt/ros/jazzy/setup.bash && cd /home/terry/ddsm_car_ws && rosdep install --from-paths src --ignore-src -r -y`

- [ ] **步骤 3：构建工作空间**

运行：
`source /opt/ros/jazzy/setup.bash && colcon build --symlink-install`

预期：`explore_lite` 和 `ddsm_car_control` 构建成功。

### 任务 3：验证与收尾

**文件：**
- 不修改运行中节点

- [ ] **步骤 1：确认包可见**

运行：
`source /opt/ros/jazzy/setup.bash && source install/setup.bash && ros2 pkg prefix explore_lite`

预期：输出 `/home/terry/ddsm_car_ws/install/explore_lite`。

- [ ] **步骤 2：确认 launch 参数**

运行：
`ros2 launch ddsm_car_control ddsm_bringup.launch.py --show-args | grep -E 'explore|mode'`

预期：显示 `mode`、`enable_explore`、`explore_params_file`。

- [ ] **步骤 3：不启动自动探索**

完成后不运行 `mode:=explore`，只提供用户启动命令。
