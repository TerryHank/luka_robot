# RK3588 → Orin NX 导航核心软件迁移（已完成离线验证）

源：`cat@192.168.3.150`，目标：`nvidia@192.168.3.251`。两端 Ubuntu 22.04/ARM64，ROS 2 Humble。原板代码、地图、服务保持原样。

源快照 `source_20260908.tgz` 的 SHA256：`d48d23bfd0be5ce925f1d60a1bcc6eb8abe569c3bd2daf632d3545b51d5f0d90`。

目标工作区：`/home/sunrise/luka_ws`。迁移 src、config、maps、tools、scripts、vendor 和原启动脚本，重新编译；未复制原 build/install。将文本配置 `/home/cat/` 改为 `/home/nvidia/`。当前楼层仍为 floor_4。

软件验证入口 `start_nx_offline.sh` 固定使用 ROS_DOMAIN_ID=87、ROS_LOCALHOST_ONLY=1，禁用电机、IMU、雷达、自动定位旋转、巡航任务及其他运动入口。使用单机 CycloneDDS 配置，最多 120 个自动 participant，导航模式用 enable_nav=auto 避免强制 true 同时启动其他模式分支。该入口只验证迁移后的 ROS 节点、插件与地图加载，不验证实车定位或行驶。

使用 Ubuntu 发行版的 cv_bridge 替代原 OpenCV 覆盖包；奥比驱动关闭 Rockchip 硬件解码，使用 ARM64 SDK。原 RKNN 人体跟随及依赖 RK3588 的模型后端不能认定已迁移，保持未启动。语音和语言服务的源码随工作区迁移，外部模型和音频设备尚需单独验收。

用户明确要求先完成软件，之后接硬件。NX 当前未连接底盘串口，雷达有线口未连接。不会启动原 `restart_nav_reset.sh`，它包含实车驱动和任务恢复流程。也不会把 NX 加入原车的 ROS 通信域发出运动命令。

视觉服务已改为按需加载 LocateAnything，空闲 30 秒卸载，录制相机继续工作；该行为已通过实际加载、推理、卸载测试。完整导航暂停/恢复联锁仍需在硬件接入后验证停车与定位反馈，不以启动进程代替停车确认。

## 2026-09-08 验收结果

- ROS 2 Humble、Nav2、SLAM Toolbox、robot_localization、CycloneDDS 及所需开发依赖已安装。
- 14 个工作区包重新编译成功，包括底盘控制、RPLIDAR、Odin、奥比相机、探索、地图/语义地图、语言指令节点；cv_bridge 使用系统版本。
- 补齐奥比源码缺失的 image_publisher 构建/运行依赖，修改仅在 NX 迁移副本中。
- 6 份地图 YAML 均找到对应图像；四楼实际发布 429×271 栅格，分辨率 0.05 米。
- 用原车 nav2_mecanum_mppi_params.yaml 测试，MPPIController 和 SmacPlanner2D 加载成功，planner_server/controller_server 均达到 active。
- 上述验证由 validate_offline.py 临时发布 map→odom→base_link 的测试坐标，仅限隔离 ROS 域；没有真实定位、没有导航目标、没有电机节点。测试结束后全部测试节点退出。
- 核心选定回归：46 通过、3 失败。3 个失败均在 3588 原系统复现，属于现行双雷达/避障实现与旧测试断言不一致，没有修改原车参数来迎合测试。语言解析及楼层逻辑另 13 项通过。
- 来源快照、构建脚本、补丁脚本、测试脚本及日志保存在本目录。证据：build.log、core_tests.log、source_baseline_tests.log、agent_tests.log、offline_validation.json、offline_startup.log、model_idle_test.json。

没有安装小车导航的开机自启动或让 NX 接管原车。现有 8091 视觉页面继续运行。硬件接到 NX 后还需核对设备权限、串口身份、雷达网段、轮向/里程计、IMU、相机外参，再验证停车联锁与低速导航。RKNN 人体跟随、原板语言模型推理后端、语音设备和原小车控制网页未作为本次导航核心迁移的已验收功能。
