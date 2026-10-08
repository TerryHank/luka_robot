# Luka 工作区包与功能唯一性核对

核对日期：2026-10-08。目标：sunrise@192.168.3.150:/home/sunrise/luka_ws。
基线：e7d5c830ff3dba1fa441ebaed3e88aca38ef749a；本轮未提交/推送Git。

## 结论

- **20个参与构建的包名唯一**；包含被COLCON_IGNORE排除的依赖源码，共24个物理包名，也没有重名。
- 跟随核心与接口适配是分层关系；兼容包/仪表盘只能转发官方启停，不保留第二套运动算法。
- 以当前已验证的实现和现用参数为基准。本轮没有盲目升级SDK/所有第三方依赖。
- 官方tros_person_following develop实时核对仍为202e8c8a04dc41e3d3771daa131b852cc24f7c0d。
- 251份历史/被替代源码、测试或重复配置移出当前源码树。原有修改和回退文件按校验值保留。
- 根目录规范、源码唯一性检查通过，源码符号链接无断链；两个过期安装配置链接已移除。

## 重叠功能对照与实际处理

| 重叠项 | 原实现/副本 | 当前保留实现 | 处理与边界 |
|---|---|---|---|
| 人体跟随运动 | HOG person_follow_node/demo；nx_follow直接速度控制；自定义map/detour/range控制；HTTP selected bridge | tros_person_following + s100_person_following_integration | 旧算法及专属测试归档；仪表盘只调用/person_follow/enable_follow，不发布Twist或Nav2 Goal |
| 旧跟随入口 | luka_person_following、selected_bridge、selected_follow.launch、preview脚本 | start_official_person_following.sh → 新版Launch | 原名称保留薄兼容层；无额外TF/感知节点；默认dry_run、跟随关闭 |
| 人脸与指定目标 | person_follow的人脸登记/识别/身份数据 | 原人脸功能继续保留 | 人脸识别不等同于官方MOT指定身份跟随。旧profile/track跟随请求明确拒绝，不暗中跟随任意人 |
| 相机采集 | ROS驱动入口与原生shared-frame视觉入口 | 对应协议入口继续保留 | 两种客户接口各有独有用途，共享Astra文件锁，当前入口不能同时持有设备；直接绕过入口手工运行程序不在此保证范围 |
| 导航启动 | scripts内/home/nvidia/ddsm_car_ws旧路径脚本与现用NX启动 | system/bringup/start_nx_navigation.sh；统一restart_nav_reset.sh模式 | 旧启动名只转发；SLAM转发MODE=slam，不暗中启动explore；status使用当前环境，stop只停止归属systemd的导航/定位服务 |
| MOT参数 | 集成包mot_config.json与核心iou2_method_param.json相同 | 核心config/iou2_method_param.json | 删除副本，Launch和测试消费同一文件 |
| 三份相同Nav2配置 | dwb_clean、lattice、dwb YAML字节相同 | nav2_mecanum_dwb_params.yaml | 两个旧名为源码内部兼容链接；现用nx_nav2.yaml等独立参数不改变 |
| 评估代码副本 | evaluator内两份YOLO26完整实现 | perception/person_follow内实际实现 | evaluator旧名改为链接，只有一份物理源码 |
| 重复测试副本 | nav_llm_agent包目录与test目录同一test_agent_parsing.py | test/test_agent_parsing.py | 不在运行包中再携带一份相同测试 |
| 旧版本文件 | before/pre/bak/orig、backup目录及旧跟随验收脚本 | 当前文件与最新测试 | 校验后移到工作区外归档，Git历史未清除 |

## 参与构建的包清单

| 包 | 核对版本 | 功能/角色 | 结论 |
|---|---|---|---|
| ai_msgs | 2.0.1 | 感知消息接口，不是感知算法 | 保留 |
| ddsm_car_control | 1.0.0 | 现有底盘驱动、安全过滤及特定硬件后端 | 保留 |
| explore_lite | 1.0.0 | 自主探索功能，与定位/导航互补 | 保留 |
| explore_lite_msgs | 1.0.0 | 探索消息接口 | 保留 |
| hobot_mot | 2.0.2 | 官方多目标跟踪；唯一当前MOT实现 | 保留 |
| hotel_semantic_map | 0.0.1 | 语义地图服务 | 保留 |
| hotel_semantic_map_msgs | 0.0.1 | 语义地图接口 | 保留 |
| luka_audio | 0.1.0 | 音频I/O、ASR/TTS等底层音频能力 | 保留 |
| luka_person_following | 0.1.0 | 兼容名称；只转发新版入口，无第二套控制实现 | 保留 |
| luka_xiaozhi | 0.1.0 | 语音助手集成层，与音频包互补 | 保留 |
| nav2_bringup | 0.0.1 | Nav2标准启动接口；现用定制入口在system/bringup | 保留 |
| nav_llm_agent | 0.1.0 | 高层语言命令适配，不是另一个底盘驱动 | 保留 |
| orbbec_camera | 1.5.21 | 唯一ROS Astra/Orbbec驱动包 | 保留 |
| orbbec_camera_msgs | 1.5.21 | 相机消息/服务接口 | 保留 |
| orbbec_description | 1.5.21 | 机器人/相机描述资源 | 保留 |
| rplidar_ros | 2.1.4 | RPLidar驱动，保留不同设备型号入口 | 保留 |
| s100_person_following_integration | 0.1.0 | S100感知和接口适配层，复用核心 | 保留 |
| teleop_twist_keyboard | 2.4.1 | 手动控制工具，与自动导航互补 | 保留 |
| tros_person_following | 0.1.0 | 唯一人体跟随目标生成与状态机核心 | 保留 |
| waterplus_map_tools | 1.0.0 | 地图/航点工具与接口，非第二个SLAM | 保留 |

另外4个被忽略的包：multirobot_map_merge（ROS1源码）、sensevoice_ros2、hobot_tts、cv_bridge。
它们各有独立用途/依赖角色，不与当前src内其他包重名。本轮未将其恢复为ROS2参与构建，也不宣称这些独立源码已全部构建通过。

## 有意保留的相同内容

- 同一demo.sh/check.sh在不同合同序号目录中属于带目录上下文的兼容入口，不是18套功能实现；都调用共享Launch/检查逻辑。
- Orbbec/RPLidar不同设备型号入口即使模板相同仍保留上游公共接口，未修改第三方设备兼容范围。
- SDK/vendored Eigen、ggml、ALSA头文件和资源模板属于依赖封装，不把它们当成重复业务节点删除。
- 语义地图默认模板与floor_1实际实例当前相同，但一份是模板、一份是部署配置，保留独立编辑语义。
- common/legacy中的audio.env、路线/运行日志、旧说明链接等仍存在实际引用，受保护未盲目删除。它们不是第二套运动实现。
- 根目录的build/install/log为派生产物；没有把相同安装拷贝误算成第二份源码包。

## 验证

- luka_person_following、s100_person_following_integration、ddsm_car_control三个受影响包重新构建通过。
- 官方跟随核心22项、官方MOT1项、官方融合1项、图像/配对适配1项，共25项通过。
- 新命令兼容层、无速度发布、身份语义拒绝、在途停止/超时迟到回复、相机互斥、兼容Launch，以及保留的选人/语音/运动路径安全测试，共16项通过。
- **本轮相关41项测试通过**；colcon的29项汇总包含4个CTest汇总项，不重复计入业务测试数。
- Node.js语法、Python AST、bash -n、Git diff空白检查及归档SHA256检查通过。
- 相机互斥测试在占用锁下直接验证入口拒绝，未启动新的相机或实车运动。
- 本轮没有真实运动目标，没有重启既有机器人应用服务。

### 全量测试限制

扩展检查发现现有test_voice_routing.py与test_object_bring_voice.py共8失败、2通过。
这6个相关实现/测试文件没有本轮diff；在清理前提交e7d5c83提取的隔离基线再次运行，得到完全相同8失败。
主要涉及旧bring_job接口、旧巡航解析预期和缺少generation的旧测试夹具；本轮未用旧实现覆盖现用代码来迎合它们。
因此不能称全工作区测试全部通过。真人跟随、真实Nav2/外参和落地验收仍按上一阶段要求待验证。

## 可恢复归档

位置：/home/sunrise/luka_archives/workspace-uniqueness-20261008

- manifest.json：每个归档/替换前文件的路径、原模式与SHA256，共269条已校验。
- originals/：替换前原文件，含用户原有改动。
- retired/：从当前源码树退役的文件，保持原相对路径。
- uncommitted-before.patch、head-before.txt、AGENTS-before.md：操作前Git/规则证据。
- baseline_tests/：重现既有8项失败的未修改基线。

恢复时逐项对照manifest，不将整套旧目录覆盖回src，不恢复并行旧跟随控制器。
没有删除地图、模型、录制、身份库、SDK依赖或Git历史。

## 后续唯一性门控

根AGENTS.md已要求修改包/入口后执行：

```bash
cd /home/sunrise/luka_ws
python3 src/system/scripts/check_workspace_root.py
python3 src/system/scripts/check_workspace_uniqueness.py
```

权威功能归属：src/common/config/functional_owners.json。
检查包括所有物理package.xml（含忽略依赖）、退役控制器禁止恢复、兼容层禁止新建publisher/重复Node，以及共享文件别名必须指向同一物理实现。

当前官方跟随入口：

```bash
bash /home/sunrise/luka_ws/src/system/scripts/start_official_person_following.sh
```

默认为候选观察且follow关闭，不自动发送实车目标。相机及定位/导航按既有环境复用，不能重复启动。
