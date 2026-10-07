# 露卡从 Orin NX 迁移到 RDK S100（软件阶段）

目标板：`sunrise@192.168.3.214`，工作区：`/home/sunrise/luka_ws`。原 NX 仍在运行；底盘、双雷达、双目相机、麦克风与扬声器尚未改接到 S100。

## 已落地

- 复制 ROS 2 源码、四楼地图与配置、航点、产品账号数据库、声纹数据库、人脸档案、物体记忆数据、双目标定文件及离线语音模型。迁移目录仅 `sunrise` 可进入。
- 安装 ROS 2 Humble 的 Nav2、SLAM Toolbox、robot_localization、Joy、Cyclone DDS 和 colcon；编译底盘控制、导航代理、地图服务、雷达驱动等核心包。
- 本地 Qwen3-4B Q4 模型用 ARM CPU 版 llama.cpp 运行，接口绑定 `127.0.0.1:8092`。导航代理保持 `dry_run=true`。
- 本地 sherpa-onnx 唤醒、SenseVoice ASR、Matcha TTS 在无音频设备的情况下通过模型加载与合成测试。
- 人体检测适配 S100 BPU YOLO11n；人脸/外观识别代码和原身份库已复制，但尚无相机实测。
- 物体识别兼容接口 `127.0.0.1:8096` 用 S100 BPU YOLO11n COCO 80 类，能识别有限类别；不等同于 NX 的 NanoOWL 开放词表或 YOLOE 家居词表。
- 监控和客户页面可在 `http://192.168.3.214:8503/`、`/user` 打开。**现在是只读验证模式，所有 POST 操作返回 503，不会启动小车。**

## 服务

`luka-ws-dashboard`、`luka-ws-chat`、`luka-ws-agent`、`luka-ws-object-api` 已设置开机启动。查看：

```bash
ssh sunrise@192.168.3.214 'systemctl --no-pager --type=service --state=running | grep luka-s100'
```

`luka-ws-vision` 与 `luka-ws-people` 的服务文件已安装，但**保持 disabled / stopped**；双目相机接入并复核标定后再启动。
底盘、双雷达、定位、导航、手柄、语音的 `luka-ws-hardware@{manual_base,sensors,localization,navigation,gamepad,voice}` 模板服务也已安装，全部 disabled；音频设备需要先写入本机 `/home/sunrise/luka_ws/common/legacy/audio.env` 的 `NX_MIC`、`NX_SPEAKER`。
音乐播放依赖的 `mpv` 已安装；NX 的 `asoundrc.NX.template` 仅作为参考保存，接好扬声器后需按 S100 上的声卡名称配置 `luka_mix`，当前未试听。

## 实测与限制

- BPU YOLO11n：448×448 静态图推理约 0.06 秒；测试图识别猫、沙发。`/infer_image` 查询“柜子”会明确返回不支持，避免虚构结果。
- 板载 YOLOE 4585 类模型也做了静态测试，约 0.05–0.08 秒/帧，但在旧场景图上把背景识别成“水箱”“实验室”等，暂不接入记忆库，以免生成错误位置。
- CPU Qwen3-4B：短问答 21 token，约 3.4 秒、8.9 token/秒；经精简代理提示词后，“你好”首句约 5 秒。明确的巡航、找物、导航、停车命令走确定性路由；陌生表达需要模型判别，测试英文 “Hello” 约 20 秒，仍需继续优化。
- Matcha TTS：短句加载加生成约 3.6 秒。当前音色模型的训练数据仅限非商业使用，**不能直接作为客户版语音包交付**。
- 导航、跟随、双目深度、声源定位、语音收发均未做 S100 实车验收；需要外设连接后逐项调试。旧奥比相机驱动、NVIDIA TensorRT/CUDA 引擎不可用于 S100。
- 这是一份 2026-09-26 的数据快照。正式切换前必须从 NX 再同步最新账号、身份、地图与记忆数据，并校验数据库完整性。

## 后续接线后验收顺序

1. 枚举并固定 USB/串口/音频设备路径；验证双雷达、底盘编码器、双目左右帧同步、麦克风和扬声器。
2. 静止状态验收 TF、双目尺度、融合扫描、AMCL 重定位与地图一致性。
3. 低速空场测试手柄/急停/碰撞保护，再启用 Nav2 与自动巡航。
4. 用新相机重新验证人脸录入、人体背影跟随与断锁找回；用现场图像调 BPU 物体识别并评估需要转换的开放词表模型。
5. 完成语音闭环、产品账号操作与客户页面验收后，解除 S100 只读和 `dry_run`，再停用 NX。
