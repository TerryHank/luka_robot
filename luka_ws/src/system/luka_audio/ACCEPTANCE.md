# 2026-10-08 本地语音部署验收

目标：`sunrise@192.168.3.150:/home/sunrise/luka_ws`。
新增独立 ROS 包 `src/system/luka_audio`；保持 source/data 分离。

| 检查 | 结果 | 证据或限制 |
| --- | --- | --- |
| 机器人 C++/Python 构建 | PASS | colcon build luka_audio，原生 RDK ASR/TTS 与 AIUI SDK 适配器编译链接成功 |
| 串口帧/路由单测 | PASS | 8项：校验、分帧、尺寸限制、唤醒去重、在线成功、失败回退与恢复、缺凭据、取消不重试 |
| RDK TTS→ASR 往返 | PASS_OFFLINE | 合成“你好，今天的天气怎么样。”，识别“你好，今天的天气怎么样？” |
| TTS PCM幅度 | PASS_OFFLINE | 修正 WeTTS float 值为16-bit PCM单位，检查削顶率<1%、RMS在50..15000；避免错误乘32767 |
| ROS 录音回放 | PASS_INTEGRATION | 模拟板载事件+录音回放，实际原生 ASR；一次识别，llm_command为0；隔离域187复验 |
| 后端失效回退 | PASS_INTEGRATION | 原生 AIUI缺配置返回失败，同一录音转本地并成功；不是联网账号验收 |
| 取消 | PASS_INTEGRATION | 运行中的后端进程被取消，2秒内结束，取消不触发fallback |
| 当前音频板接口 | PASS_READ_ONLY | USB XFM-DP-V0.0.18；16kHz单通道S16_LE；可读到固件唤醒/方向日志 |
| 实际扬声器输出 | PASS_PLAYBACK_PROCESS | ROS TTS请求合成并完成aplay，37888采样点；人耳效果尚未确认 |
| 服务运行与启动 | PASS_RUNTIME | luka-ws-hardware@voice.service active/running、enabled，最终检查NRestarts=0 |
| 当前配置 | PASS_RUNTIME | backend_mode=rdk、dispatch_commands=false；等待硬件唤醒、frontend_ready=true |
| 所有者 | PASS_RUNTIME | 一个网关，一个arecord麦克风进程；voice/doa一个发布者；无第二套KWS/ASR录音节点 |
| 结构与包名 | PASS_STATIC | 根目录检查通过；18个colcon包，无重复包名；vendor/venv有COLCON_IGNORE |
| 新鲜现场唤醒→说话→识别 | PENDING_LIVE | 35秒观察没有新的现场唤醒，也无实车命令；需操作者说“露卡”后说测试句 |
| 新版M260C/R329串口 | PENDING_HARDWARE | 帧解析和握手有代码/离线测试；当前板采用ADB，固件标识sun50iw10，不能冒充新版验收 |
| AIUI账号/联网/真实断网 | DEFERRED | 按用户要求先部署本地；无自有凭据，未启用云链路 |
| 小智联网对话 | NOT_IN_THIS_DEPLOYMENT | 官方客户端可选，固定版本见UPSTREAM.json；没有作为KWS，也未与当前入口同时录音 |
| 语音导航、声源趋近、声纹、离线自由对话 | NOT_ACCEPTED | 本轮为ASR/TTS本地链路，未迁入旧扩展、未发动作；合同演示状态继续部分完成 |

实测原始记录位于 `~/luka_data/runtime/audio/acceptance/`：
`tts.log`、`asr.log`、`tts.pcm`、`live_local.json`。
构建/测试输出位于 `~/luka_ws/{build,install,log}`，不加入源码版本。

保留原有NX_MIC/NX_SPEAKER配置、DOA方向校准和旧网关代码。
DOA运行状态迁到 `luka_data/runtime/audio/xfm_doa.json`，兼容读取器同步适配。
旧网关可通过 `LUKA_VOICE_BACKEND=legacy` 选择；重新启动voice服务后生效。
本轮没有重建或验收其他17个包的功能，没有发布底盘速度或导航目标。

## 后续联网上线

2026-10-08用户提供完整AIUI凭据后，ASR/TTS真实请求通过，当前backend_mode=auto。
语义对话仍返回SDK20001，luka_xiaozhi自动使用本地Qwen回答。
历史表中的“AIUI未启用/rdk固定模式”是前一阶段结果，当前状态以上述后续结果为准。
小智部署与无公网测试见 `../luka_xiaozhi/ACCEPTANCE.md`。

## 最终网络路由（当前生效）

后续真实核验确认：供应商SDK为6.6.0001.0047，当前应用的v3 WebAPI可用；
旧v2/SDK NLP报错不能代表云应用没有个性化大模型能力。
当前联网ASR、对话、TTS全部使用AIUI，只有统一公网监测确认offline才用本地模型。
在线认证、权限、服务错误不触发本地补答；unknown状态不猜测断网。
音频14项Python测试与C++错误分类、小智20项Python测试通过。
最新联网回答和实际播放8.52秒；隔离进程真断公网后，实际监测确认offline才运行
本地ASR/Qwen/TTS，3轮10.69、6.40、5.50秒。没有发布机器人动作。
此前表中local固定对话、任意云错误自动回退、AIUI大模型不可用均为历史阶段，
当前部署以本节和luka_xiaozhi最新验收记录为准。
