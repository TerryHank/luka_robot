# Luka 本地唤醒与语音后端

源码：`~/luka_ws/src/system/luka_audio`。模型：`~/luka_data/ml_models/audio`。
临时 PCM、DOA 状态与验证记录：`~/luka_data/runtime/audio`。

## 实际分工

| 模块 | 实现与边界 |
| --- | --- |
| KWS、声学前端、DOA | 麦克风板固件；上位机仅读事件和 16 kHz 单通道 S16_LE UAC |
| 当前硬件事件 | XFM USB ADB 日志；已读到 `lu4 ka3`（露卡）唤醒与方向记录 |
| 新版 M260C/R329 事件 | 按资料实现 A5/01 串口帧、校验、分帧和握手；需实际新板验收 |
| 离线 ASR | D-Robotics/sensevoice_ros2 的 GGUF 核心与固定版本库 |
| 离线 TTS | D-Robotics/hobot_tts 的本地 WeTTS 核心与模型 |
| 联网 ASR/TTS | 用户提供的 ARM64 AIUI SDK；独立进程处理 PCM，ASR/TTS已实测；语义对话另见luka_xiaozhi验收记录 |
| 小智 | 改造版luka_xiaozhi是本机总控；联网使用AIUI v3云对话，确认断网才使用本地Qwen |

当前设备 USB 名称为 XFM-DP-V0.0.18，固件设备树标识 `sun50iw10`、CPU 为四核 A53。
这尚不能作为“当前就是新版 R329”的证据。没有刷机或改板载唤醒词。
新版串口适配仅在明确指定音频设备时启用，不扫描或占用底盘/IMU串口。

## 一键启动与停止

```bash
sudo systemctl start luka-ws-hardware@voice.service
sudo systemctl stop luka-ws-hardware@voice.service
```

现有 `src/system/bringup/start_nx_voice.sh` 默认转到统一入口。
配置沿用 `src/common/config/audio.env` 的 NX_MIC、NX_SPEAKER。
当前部署 `LUKA_AUDIO_MODE=auto`，联网时ASR/TTS仅用AIUI，确认断网才用RDK；`LUKA_VOICE_DISPATCH_COMMANDS=false`。
说“露卡”，听到约80毫秒提示音后说一句测试语句；每次硬件唤醒采集一句话。
只说唤醒词会播放提示音，不生成对话回答。提示音是固定PCM，不调用本地或云端TTS。
没有唤醒时不执行识别。播放期间暂停采集，并等待回声消退。

接口：`/voice/hardware_wake`、兼容 `/voice/doa`、`/voice/recognized_text`、
每秒 `/voice/status`。`/voice/tts_text` 的 std_msgs/String 输入可播放任意短句。
支持 `/voice/control` 的 enable/start、disable/sleep/stop、cancel。
取消识别或合成会终止后台进程，取消操作不会转到另一个后端重做。
识别只在 `dispatch_commands=true` 时发送 `/llm_command`，不直接发速度或导航目标。

```bash
source ~/luka_ws/src/system/environment.bash
ros2 topic echo /voice/status
ros2 topic echo /voice/recognized_text
ros2 topic pub --once /voice/tts_text std_msgs/msg/String '{data: "本地语音链路已经启动"}'
```

## 联网模式（已启用AIUI ASR/TTS）

把自有 AIUI 配置放在 `~/.config/luka_audio/aiui.cfg`，权限600。
模板 `config/aiui.cfg.example` 不含可用凭据；SDK和凭据不上传 Git。
将 audio.env 的 `LUKA_AUDIO_MODE` 改为 `auto` 后重启 voice 服务。
通过统一公网监测选择后端，一次业务请求成功才报告AIUI healthy。
网络online时认证、权限、SDK服务错误或超时只报错，不切本地；确认offline才使用RDK。
网络unknown时不猜测断网。公益站点与AIUI的TCP探测只判断公网可达，不代表云端鉴权通过。
一次请求的原生进程隔离，旧请求不会把结果发到新会话。
没有“能 ping 就认为云端可用”的判定，也不同时启动多个录音程序。

串口新板：设置 `LUKA_AUDIO_FRONTEND=m2_serial` 和
`LUKA_AUDIO_SERIAL=/dev/明确的音频板设备`。串口恢复时丢弃旧接收缓冲；
初始化第一秒只做握手，不转发唤醒。串口路径必须经过硬件身份确认。

## 构建、依赖与恢复

```bash
source ~/luka_ws/src/system/environment.bash
cd ~/luka_ws
MAKEFLAGS=-j1 colcon build --base-paths src --packages-select luka_audio --parallel-workers 1
colcon test --packages-select luka_audio
```

固定上游版本和模型校验值见 `UPSTREAM.json`。必要 SDK 位于 `src/common/vendor/sensevoice_sdk` 和 `src/common/vendor/wetts_sdk`；旧 ROS 包装源码在工作区外归档。当前使用的 `audio_venv` 与私有 AIUI vendor 排除 Git/colcon。
用 `scripts/bootstrap.sh` 重建官方依赖/模型/venv；AIUI SDK需从用户资料包单独恢复，
其 `include/aiui` 和 `libs/arm64` 放在 `vendor/aiui`。没有 SDK 也可构建 RDK 本地链路。
VAD沿用已部署的 `luka_data/ml_models/common/voice/vad/silero_vad.onnx`，缺失时需恢复该文件。

原有软件唤醒入口保留：audio.env 可设置 `LUKA_VOICE_BACKEND=legacy` 再重启服务。
旧声纹、对象播报、语音跟随扩展仍在原代码中，本轮未迁入统一入口，未验收这些扩展。
不要同时启动旧网关、小智原版、sensevoice原始录音节点或 hobot_tts 原始播放节点。

本地识别/合成不等于离线自由对话：自然语言理解仍取决于现有 Agent/模型服务。
板载 AEC 的播放参考线接法未现场确认；本实现没有宣称全双工打断已经可用。

没有声音时先检查 `aplay -l` 和 `amixer -c Device sget PCM`。
当前唯一播放设备为C-Media USB声卡；2026-10-08发现PCM为0%（-37dB），
已调到65%并用`sudo alsactl store 1`保存。播放完成不等于实体扬声器可闻，
还需确认3.5毫米输出、功放供电和实际接线。`/voice/status`只发布安全错误码、
错误范围和超时标志，不转发SDK日志或凭据。

当前小智总控见 `../luka_xiaozhi/README.md`：联网识别、个性化对话、合成都在AIUI；
仅确认断网时使用本地SenseVoice、Qwen、WeTTS。v3云对话已真实通过，旧SDK的NLP错误
不是云应用能力不可用的证明。音频SDK适配忽略旁路NLP错误，保留其真正识别/合成错误。
