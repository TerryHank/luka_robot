# NX 软件迁移续作，2026-09-10

网页入口：http://192.168.3.251:8503/ 。本次仅启动 nx-dashboard、nx-agent 两个服务，未设置开机自启动，未启动底盘或导航。原车 3588 源码、服务和配置未修改。

## 已部署与验证

- tools/nx_dashboard.py 复用原车监控界面。默认加载四楼保存地图（429×271，0.05 m），支持选择四个楼层地图。相机由已有 8091 服务代理提供，不重复占用 USB 相机。真实位姿为空，不使用伪造定位。
- 页面醒目标注软件验证模式，服务端拒绝导航、跟随、运动模式切换、航点写入、关闭服务等 POST。只允许浏览地图切换和中文指令测试。
- start_nx_agent.sh 使用本地 8092 Qwen3 4B，dry_run=true，独立的离线任务状态路径；ROS_DOMAIN_ID=87、ROS_LOCALHOST_ONLY=1，与原车隔离。支持现有 15 项能力的指令解析，运动命令只回报 dry_run。
- HTTP→ROS→Qwen→网页回执实测：中文问候回答成功，开始巡航解析为 patrol_start(loop)，停止解析为 cancel_all。测试监听的 cmd_vel、酒店目标、巡航开始/停止话题均无消息。测试未覆盖所有运动话题；也没有启动任何执行节点。
- 原车 voice 模型复制到 /home/sunrise/luka_ws/common/models/voice，传输归档两端 SHA256 相同：bc1b2a17e9af373542d09c3a66232034788af845ac8a1e1ced8948b88a407a1a。
- 安装与源板相同的 sherpa-onnx 1.13.6 / sherpa-onnx-core 1.13.6 ARM64 运行库。中文 TTS 合成约 3.10 秒音频，耗时 2.63 秒；SenseVoice 识别耗时 0.18 秒，第二次识别准确。第一次合成识别出现“小车→校车”同音误识别，因此不能把这次小样本当成识别准确率保证。
- 唤醒词模型成功加载，静音输入无触发；尚未验证真人唤醒率与音频硬件。start_nx_voice.sh 要求显式指定 NX_MIC / NX_SPEAKER，不沿用 3588 的 ALSA 卡号，未启动常驻录音。
- 语言解析/楼层回归 13 项通过；能力注册与工作流另 6 项通过。现有 CPU HOG 跟随控制逻辑、传感器丢失停止/不自动恢复，以及诊断快照测试通过。没有启动跟随节点。

## 操作

查看：systemctl status nx-agent nx-dashboard

停止本次新增服务：sudo systemctl stop nx-agent nx-dashboard

再次启动：sudo systemctl start nx-agent nx-dashboard

原有视觉页面 8091、本地聊天页面 8092 保持运行。新增服务不自动加载 Qwen，收到需要推理的指令时才调用。

证据：nx_ui_acceptance.json、nx_voice_acceptance.json、test_nx_ui.py、test_voice_models.py。音频保存在 NX /home/nvidia/nx_voice_test.wav。

## 尚待实车阶段

串口/轮向/里程计、IMU、雷达、真实地图定位与导航；麦克风/扬声器和真人语音；视觉跟随实际检测质量；导航暂停、停车确认、模型互斥及恢复联锁。原 RKNN 模型后端没有转换成 NVIDIA 后端，本次验证的是工作区现有 CPU HOG 跟随代码。不得据此宣称全车功能已完成实车验收。
