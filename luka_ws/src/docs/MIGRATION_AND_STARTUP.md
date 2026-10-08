# Luka 功能对比与启动说明

实施日期：2026-10-03；目标：sunrise@192.168.3.150。

> 后续更新：新工作区已切换为 Astra Pro Plus + Orbbec SDK v1.10.37，RGB/深度均约30Hz，已恢复有效深度。最新配置、服务状态及命令见 [Orbbec 安装与验收](ORBBEC_INSTALL_AND_ACCEPTANCE.md)。下文单目设备和服务已停止的叙述属于驱动切换前的历史验收记录。

除明确排除的 Odin 驱动外，luka_s100 的运行功能源码、模型、配置、账号/身份和记忆数据已按 luka_ws 的分类目录复制。原工作区的源码、模型、配置、数据库和旧 systemd 定义未修改。旧服务已停止并取消开机启动；新服务安装后也未启用开机启动。最后成功检查时，两套服务均已停止。

## 切换前的单目相机静态验收（历史记录）

用户已确认当前相机不是旧标定对应的物理相机。当前设备为 Sonix SN0001 单目 UVC，相机路径为 `/dev/v4l/by-id/usb-Sonix_Technology_Co.__Ltd._USB_2.0_Camera_SN0001-video-index0`。旧 Sunplus 相机的双目标定不可套用。

新工作区已新增 `perception/spatial_memory/monocular_camera.py`，视觉服务默认 `NX_CAMERA_SOURCE=uvc_mono`，人员检测沿用共享帧接口。视觉与人员服务明确取消旧标定环境变量，报告 `metric_depth_available=false`；无效深度不产生距离或空间坐标。YOLOE 改为通过配置读取单目高清快照，保留原双目快照地址作为双目模式默认值。旧工作区与旧标定文件保持原样。

已验证：

- 单目预览和高清快照 HTTP 200；人员检测约 8 fps，`motion_enabled=false`。
- BPU COCO80 从实际相机帧检测到 3 个结果，一次推理约 0.009 秒；YOLOE-26n 从 1280×960 帧完成二维推理，约 1.13 秒。结果数量只代表这次采样，不代表精度评估。
- 20 项页面、状态、功能目录与前端资源 HTTP 检查全部通过。聊天模型实际返回“测试通过”，约 1.31 秒。服务启动后需要等待模型与页面初始化，过早请求曾返回未就绪。
- Matcha 离线合成约 3.32 秒音频，SenseVoice 识别为“你好，路卡相机功能测试完成。”。未播放音频、未打开麦克风；这不等于麦克风/扬声器端到端验收。
- 12 秒静态订阅收到上激光、下激光、融合激光各 121 帧，IMU 1201 帧，只读轮速里程计 120 帧。地图为 429×271，分辨率 0.05 米。轮速采样为零。
- 定位服务可以加载地图及 AMCL，但 AMCL 尚待可靠初始位姿；未发初始位姿、导航目标、巡航或跟随任务。

检查中发现原定位 systemd 附加配置含 `Wants=...hardware@manual_base.service`，启动它会拉起底盘服务。我漏查这条依赖，发现后立即停止相关服务。第一次只读里程计因此发生串口并发访问；第二次改用独立临时定位进程，底盘控制、导航与 boot-localize 均保持 inactive，只读里程计恢复。此依赖保留原完整启动行为；静态启动模式不含定位服务。最后本次启动的服务已停止。

回归结果（同一批现有测试，新旧对照）：

| 测试范围 | 新工作区 | 旧工作区 |
|---|---|---|
| agent | 18 通过 / 1 失败 | 18 通过 / 1 失败 |
| control | 220 通过 / 28 失败 | 220 通过 / 28 失败 |
| runtime | 74 通过 / 9 失败 | 74 通过 / 9 失败 |
| 人员识别与跟踪核心 | 174 通过 / 1 失败 | 174 通过 / 1 失败 |
| 空间几何 | 8 通过（含新增单目无深度检查） | 7 通过 |

合计新工作区 494 通过、39 失败；这些失败在旧工作区同样出现。完整人员 worker 测试还在新旧两边同时发生收集错误：旧模拟夹具未提供现行 worker 导入的 `PeopleNetDetector`。没有修改旧业务行为或测试来隐藏失败。导航参数断言、巡航/物体取回旧接口、语音回复清理和弱人体重新确认等失败已记录，不能把测试结果描述成全部通过。

目标板曾因多个 VS Code 远程扩展宿主和索引进程耗尽内存，且没有交换空间。经用户授权停止远程编辑器服务后，可用内存从约 149 MiB 恢复到约 6.3 GiB。未卸载或禁用扩展；重新打开多个远程窗口仍可能重新产生占用。

**完整功能等价验收尚未完成**：当前单目设备无法恢复双目深度、可靠空间坐标及依赖距离的跟随，需要兼容的深度设备和对应标定；导航、巡航、跟随的实车运动验收按用户要求未执行。代码与数据的迁移不能代替硬件等价性及实车验收。

现在建议先用静态模式：

```bash
/home/sunrise/luka_ws/src/system/luka.sh start ws stationary
# 停止本次启动的所有新工作区服务
/home/sunrise/luka_ws/src/system/luka.sh stop ws
```

该模式启动页面、聊天、agent、物体 API、相机、人员识别和 YOLOE，不自动启动底盘、导航或定位。页面原有“一键启动”等硬件操作仍存在，不属于这个命令的静态约束。

验收证据在目标板 `/home/sunrise/luka_ws/src/evaluator/stationary_audit_20261003`；最新原文件校验位于备份的 `original-after-stationary-audit.json`：8183 个源文件变化为 0，12 个旧服务定义检查变化为 0。

## 功能包对比

以下新目录均相对于 `/home/sunrise/luka_ws`；旧 ROS 包均位于 `/home/sunrise/luka_s100/ddsm_car_ws/src`。

| 功能包/功能 | 复制前情况 | 新目录与最终状态 |
|---|---|---|
| ddsm_car_control | 所比较的 98 个源码/配置文件相同 | control/ddsm_car_control；从旧目录覆盖复制并重新构建 |
| teleop_twist_keyboard | 已有 ROS 包 | control/teleop_twist_keyboard；复制并重新构建 |
| nav_llm_agent | 所比较的 32 个文件相同，agent_node.py 落后于旧工作区 | system/nav_llm_agent；复制最新版本并重建，包含忙时请求排队和取消后丢弃旧回复的改动 |
| nav2_bringup | 已有包，缺少完整 S100 启动配套 | system/nav2_bringup；复制并重新构建 |
| rplidar_ros | 所比较的 94 个文件相同 | sensing/rplidar_ros；复制并重新构建 |
| hotel_semantic_map | 所比较的 16 个文件相同 | map/hotel_semantic_map；复制并重新构建 |
| hotel_semantic_map_msgs | 已有接口包 | map/hotel_semantic_map_msgs；复制并重新构建 |
| waterplus_map_tools | 已有航点包 | map/waterplus_map_tools；复制并重新构建 |
| explore_lite | 已有探索包 | planning/explore；复制并重新构建 |
| explore_lite_msgs | 已有接口包 | planning/explore_lite_msgs；复制并重新构建 |
| map_merge | 有源码 | map/map_merge；复制，保持原 COLCON_IGNORE |
| OrbbecSDK_ROS2 | 有源码，原来禁用构建 | sensing/OrbbecSDK_ROS2；复制，保持原 COLCON_IGNORE |
| vision_opencv/cv_bridge | 有源码，运行使用系统版本 | perception/vision_opencv；复制，保持原 COLCON_IGNORE |
| odin_ros_driver | 原新工作区有源码及构建记录 | 按用户要求从新工作区移除源码、src 兼容入口、build 和 install；旧工作区保持原样 |
| S100 底盘/雷达/导航启动入口 | 缺少整套实际运行入口 | system/bringup；复制 start_nx_*、launch 和辅助入口，修改新副本路径 |
| S100 地图定位入口 | 缺少现场入口 | localization/launch/nx_localization.launch.py |
| Dashboard、客户页、网页遥控 | 缺少完整实现 | visualization/console；与原紧密耦合的巡航、跟随和语音工具一起复制 |
| 人体、人脸身份、跟随和恢复 | 缺少完整 person_follow | perception/person_follow；含人物档案数据库和数据 |
| 相机、深度、空间记忆 | 缺少完整实现 | perception/spatial_memory；新增单目适配；双目源码保留，当前无有效深度 |
| 视觉服务、物体与语义记忆 | 缺少完整实现 | perception/locateanything_trial_20260907；含数据库和记忆数据 |
| YOLOE 开放词表找物 | 缺少服务和独立环境 | perception/yoloe26_live；含 ONNX 模型与复制后的 venv |
| S100 BPU COCO 检测 API | 缺少服务入口 | perception/object_api/s100_object_api.py |
| 双目标定 | 缺少完整配套 | sensing/stereo_calibration |
| Qwen 聊天模型及运行库 | 缺少独立聊天服务部署 | system/nx_chat；新副本 ELF 的旧 RUNPATH 改为 $ORIGIN |
| 语音闭环、声纹、音乐与巡航工具 | 仅有部分通用包源码 | visualization/console、common/models、system/music；完整工具及离线模型已复制 |
| 产品账号、用户和声纹数据 | 缺少完整配套 | system/product |
| 配置、地图、任务状态、航点 | 仍引用旧目录 | common/config、map/maps、common/state、common/runtime；新副本路径已迁移 |
| 原 vendor 依赖 | 缺少配套 | common/vendor；保留同机系统依赖 /opt、/app 等 |
| systemd 服务和外部 helper | 全部指向 luka_s100 | system/services、system/helpers；安装独立 luka-ws-* 服务 |

根目录 tools/config/maps/models/product 等和 src 下的兼容入口只链接到新工作区内部，不链接回 luka_s100。页面和工具保持原有相互导入关系，没有为了目录分类重写功能。

历史 tar 包、备份目录、缓存和 Unix socket 不作为运行功能复制。

## 默认环境

`.bashrc` 已加入：

```bash
source /home/sunrise/luka_ws/src/system/environment.bash
```

该文件加载 `/opt/ros/humble/setup.bash` 和 `/home/sunrise/luka_ws/install/local_setup.bash`，设置 DDSM_WS、ROS_DOMAIN_ID=87、ROS_LOCALHOST_ONLY=1 和 CycloneDDS。它只加载环境，不启动服务。目录本身不能作为 Bash source 文件。

重新登录 SSH 或执行 `source ~/.bashrc` 后生效。已验证 ddsm_car_control 和 nav_llm_agent 的包前缀位于 luka_ws/install。

## 启动新工作区

以下命令在远端 SSH 会话中运行：

```bash
source ~/.bashrc
# 只启动页面、聊天、指令代理和 BPU API
/home/sunrise/luka_ws/src/system/luka.sh start ws software
# 或启动完整硬件功能
/home/sunrise/luka_ws/src/system/luka.sh start ws full
# 查看状态
/home/sunrise/luka_ws/src/system/luka.sh status ws
# 停止
/home/sunrise/luka_ws/src/system/luka.sh stop ws
```

## 启动原工作区

```bash
/home/sunrise/luka_ws/src/system/luka.sh stop ws
/home/sunrise/luka_ws/src/system/luka.sh start s100 software
# 或启动原完整功能
/home/sunrise/luka_ws/src/system/luka.sh start s100 full
/home/sunrise/luka_ws/src/system/luka.sh status s100
/home/sunrise/luka_ws/src/system/luka.sh stop s100
```

启动脚本会拒绝在另一套服务 active/activating 时启动，必须先停止另一套。旧工作区通过原 systemd 服务及原安装环境启动，不改变 Bash 默认加载的新工作区环境。

full 包含底盘、传感器、定位、导航、语音、视觉/人物/找物、导航记录器、Wi-Fi 恢复定时器及 boot-localize。自动定位静态验证失败后可能使机器人旋转。实体手柄和 sonar_ros 不包含在默认完整列表中，保持本次检查时原系统未启用的状态。software 不启动硬件，但保留原执行接口，页面一键启动仍能启动硬件。

页面： http://192.168.3.150:8503/ ，客户页 `/user`。两套占用相同端口和硬件，不能同时运行。

```bash
journalctl -u luka-ws-dashboard -n 80 --no-pager
journalctl -u luka-ws-vision -u luka-ws-people -n 80 --no-pager
# 旧工作区把 luka-ws 改为 luka-s100
```

## 验证、限制和备份

- 10 个保留的实际运行 ROS 包重新构建成功；Odin 已排除。
- Python 和 Bash 语法检查通过，新 systemd 单元没有本次配置错误。
- 五个 SQLite 数据库 quick_check 均为 ok。
- 四个软件服务启动检查通过，无重启；页面、客户页、功能状态和定位状态返回 HTTP 200，聊天服务健康接口返回 ok。检查后已全部停止。
- 新软件进程映射中没有旧工作区文件，互斥启动检查通过。
- 扩展回归检查为 494 通过、39 失败；新旧对照及人员测试收集限制见上文。
- 最终哈希复核 8,183 个复制源文件，原文件变化为 0，旧 systemd 服务定义变化为 0。此统计包含随后按用户要求从新工作区排除的 Odin 源文件。
- 当前不同物理单目相机已恢复二维视觉，旧双目标定已停用。深度功能、自动定位 heading_ambiguous、实车运动与麦克风/扬声器端到端验收仍未完成。
- 新旧数据是独立复制快照，后续账号、身份、地图和记忆变化不会自动同步。

备份位于 `/home/sunrise/luka_migration_backups/20261003_183526`，含原 .bashrc、原 luka_ws、旧服务定义与启用状态、复制/哈希清单、构建/测试日志、数据库检查、原文件最终审计及 Odin 排除归档。

旧系统可用上述 s100 命令手动启动。若以后要恢复旧开机启动，依据备份中 old-service-state.json 的 enabled 条目；本次保持取消开机启动。

远端也已保存完整说明 `/home/sunrise/luka_ws/src/docs/MIGRATION_AND_STARTUP.md` 和逐项 CSV `/home/sunrise/luka_ws/src/docs/function-comparison.csv`。文档交付阶段 SSH 出现过间歇性超时，随后远端文档保存已确认成功。
