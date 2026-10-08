# 交付报告

状态：**代码集成、构建、模拟和静态验收完成；真人及实车验收待验证**。

## 修改清单

| 文件/目录（相对于 luka_ws） | 原因 |
|---|---|
| src/control/tros_person_following/src/person_following_node.cpp | 真正的dry_run决策出口；自身Goal取消与迟到回调隔离；TF/感知/地图有效性；禁用直接速度和旋转；独立LOST超时 |
| src/control/tros_person_following/include/tros_person_following/person_following_node.h | 配置、UUID/代际、诊断、优雅关闭接口；原本地参数保留 |
| src/control/tros_person_following/src/main.cpp | SIGINT/SIGTERM时在ROS退出前停跟随，保留3秒响应/取消处理 |
| src/control/tros_person_following/CMakeLists.txt | 保留组件注册，构建独立安全关闭入口 |
| src/perception/hobot_mot/src/tros_mot_node.cpp | 仅5行：没有检测的已知类型仍进入原MOT更新，正常产生消失事件 |
| src/control/s100_person_following_integration/launch/ | 独立可选启动官方感知模块；查重；默认dry_run、follow关闭；真实模式要求显式输入契约确认 |
| src/control/s100_person_following_integration/config/ | S100模型与实际640×480接口、官方MOT JSON、1.8–2.0m距离及安全默认参数 |
| src/control/s100_person_following_integration/scripts/rgb_to_nv12.py | 只做格式转换，让官方DNN保持宽高比，不改图像几何/header |
| src/control/s100_person_following_integration/scripts/pair_registered_depth.py | ≤40ms近似配对适配官方ExactTime，原深度/真实掩码保留并发布时间差 |
| src/control/s100_person_following_integration/scripts/preflight.py | 新鲜只读ROS接口/TF/Action清单，缺失返回失败 |
| src/control/s100_person_following_integration/test/ | 四个测试文件，25项已通过 |
| src/system/scripts/person_follow_environment.bash | 只加载ROS包与独立官方依赖路径，不覆盖调用者Domain/RMW |
| src/system/scripts/check_person_following.sh | 一键静态/模拟回归入口，可选实际图审计 |
| src/docs/person_following/ | 审计、架构、接口、测试、启动说明、版本校验与上游补丁 |

所有旧bridge未提交文件保持原样；本轮不启动旧HTTP/ReID选人链路。
新源目录无重复ROS包；上游完整Git reference与官方二进制依赖均在 `/home/sunrise/luka_upstream/`，不参与工作区colcon源码发现。
本轮没有提交/推送Git，也未安装开机跟随服务。

## 启动说明

### 1. 进入已有机器人ROS环境

```bash
cd /home/sunrise/luka_ws
source src/system/environment.bash
source src/system/scripts/person_follow_environment.bash
```

第一个是机器人原有环境配置；新模块环境脚本本身不会改变Domain/RMW。
已有相机在运行时直接复用；相机未运行时可使用已有入口：

```bash
bash src/system/scripts/start_orbbec_camera.sh
```

既有定位/导航的现用入口是 `src/system/bringup/start_nx_localization.sh` 和 `start_nx_navigation.sh`。
后续实车阶段可分别在独立终端启动，已有进程存在时不得重复运行；本轮未执行这两条入口。
审计发现旧 `src/system/scripts/start_nav2.sh` / `start_nav_slam.sh` 仍写死 `/home/nvidia/ddsm_car_ws`，本模块不使用它们，也未越界修改原导航系统。
实际地图、定位、安装外参和安全链必须先准备好。

### 2. dry_run

```bash
ros2 launch s100_person_following_integration s100_person_following_integration.launch.py start_segmentation:=true output_mode:=dry_run
```

该命令已实采验证，只启动新感知链路和默认关闭的跟随核心。若已有兼容分割、融合或MOT节点，分别使用对应start_*:=false复用。
启用候选生成的操作在另一个已加载相同环境的终端：

```bash
ros2 service call /person_follow/enable_follow std_srvs/srv/SetBool '{data: true}'
ros2 topic echo /person_follow/goal_candidate
ros2 topic echo /person_follow/integration_diagnostics
ros2 service call /person_follow/enable_follow std_srvs/srv/SetBool '{data: false}'
```

没有新鲜map TF/Costmap时不会产生候选；真实场景无人也不会产生人体跟随候选。
模拟/静态一键验收：

```bash
bash src/system/scripts/check_person_following.sh
# 已有实际导航系统就绪后再读取实际图；缺失返回非0
ros2 run s100_person_following_integration preflight.py
```

### 3. 后续显式 nav2_action（本轮不执行）

完成真人dry_run、真实外参/测距、现有Nav2/Costmap/运动门控验证后，先关闭dry_run进程，再启动：

```bash
ros2 launch s100_person_following_integration s100_person_following_integration.launch.py start_segmentation:=true output_mode:=nav2_action input_contract_verified:=true follow_enabled_on_start:=false
```

再通过同一个enable_follow服务人工启用。模式只在进程启动时选择，不能依靠动态改参数切换运动状态。
本次nav2_action只连接模拟Action Server验证过，没有连接真实车辆导航服务器。

## 构建复现

```bash
source /opt/ros/humble/setup.bash
source /home/sunrise/luka_ws/install/local_setup.bash
cd /home/sunrise/luka_ws
colcon build --base-paths src --packages-select tros_person_following hobot_mot s100_person_following_integration --symlink-install --executor sequential
```

二进制官方依赖为独立解包，源码可构建性不等于可重编译闭源融合。版本、校验值见lock文件；运行需要依赖目录和已有系统S100模型。

## 限制

- Astra是RGB-D；未完成StereoNet双目硬件验收，不能把本次结果宣称为双目方案通过。
- 官方融合完整源码未公开找到，使用校验过的官方二进制并在S100执行测试；enable_pub_map=false崩溃采用独立调试栅格配置规避。
- 现场没有人，真人ROI/尺寸/距离、遮挡、安装外参、实际Nav2/TF与运动性能尚未通过。
- 旋转搜索禁用；正常Goal优雅取消验证通过，强制杀进程或过晚响应仍需已有安全链兜底。
- 独立提取的官方前缀无总local_setup文件，colcon会显示该前缀警告；不影响本轮包构建与运行测试。未修改系统ROS安装。

官方参考：
- https://github.com/D-Robotics/tros_person_following/tree/202e8c8a04dc41e3d3771daa131b852cc24f7c0d
- https://github.com/D-Robotics/mot/tree/0120205146d88c3474bfc2936522e349e169fa8d
- https://github.com/D-Robotics/hobot_dnn/tree/a5d6c3312315599b03d09ce5f00a8a9761702f12
- https://d-robotics.github.io/tros_vims_doc/
