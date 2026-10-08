# 2026-10-08 最终路由验收

目标：sunrise@192.168.3.150。规则为联网AIUI全云、仅确认断网才本地推理。

| 项目 | 结果 | 证据 |
| --- | --- | --- |
| 构建 | PASS_BUILD | luka_audio、luka_xiaozhi在机器人构建安装成功 |
| 单测 | PASS | 音频15项、小智23项Python测试，另有C++错误分类回归检查 |
| 业务错误不触发本地 | PASS | 在线超时、缺凭据、云服务错误均不调用本地；unknown网络也不降级 |
| 云端个性化大模型 | PASS_ONLINE | 同一凭据v2 NLP返回20001无效参数；v3真实返回“小丸子”角色回复 |
| 云端ASR | PASS_ONLINE | AIUI实际识别16k测试PCM，“你好今天的天气怎么样”，最新实测2.61秒 |
| 云端回答与真实播放 | PASS_RUNTIME | 注入测试识别文字，dialogue_backend=aiui、TTS backend=aiui、network_state=online，实际aplay完成；8.52秒 |
| 断公网本地链路 | PASS_PROCESS_NETWORK_DENIAL | 隔离测试进程禁止公网、仅允许loopback；实际网络监测确认offline，再运行本地ASR、Qwen、TTS |
| 离线多轮 | PASS_LOCAL | 记住“小明”，下一轮正确回答；最新3轮10.69、6.40、5.50秒 |
| 恢复与取消 | PASS | 网络恢复后后续请求走云，取消不触发其他后端重做，旧回复被丢弃 |
| 当前SDK | VERIFIED | 库版本6.6.0001.0047，不能配置v3；云大模型使用官方v3 WebAPI，音频仍用已验证SDK |
| 硬件与包所有者 | PASS | 单一网关采集/播放，新小智只处理会话；无重复ROS包名；根目录检查通过 |
| 机器人动作 | NOT_SENT | 所有测试llm_command计数0；动作许可关闭，自动机器人工具未迁入 |
| 真人现场唤醒整轮 | PENDING_LIVE | 回放、注入和播放进程完成不等于真人现场验收 |
| 唤醒确认提示音 | PASS_PCM_PLAYBACK | 80毫秒固定PCM经真实Silero VAD不被判断为语音，aplay完成；真人可闻待确认 |
| 本地模型生命周期 | PASS_COLD_LOCAL | 隔离断网时按需启动Qwen，三轮22.96、7.10、6.00秒，结束后服务inactive；仅释放自己启动的实例 |
| 连说、R329串口、BPU LLM、双讲及并发压力 | NOT_ACCEPTED | 当前尚无唤醒前缓存，当前板为XFM ADB接口；不得冒充这些功能已验收 |

最新证据：

- `~/luka_data/runtime/audio/acceptance/aiui_webapi_probe.json`
- `~/luka_data/runtime/xiaozhi/acceptance/live_chain.json`
- `~/luka_data/runtime/xiaozhi/acceptance/offline_chain.json`
- build/install/log内构建及CTest结果

公网限制只用于隔离验收进程，没有断开机器人网络或修改全局防火墙。
私有凭据保持在.config目录、权限600；没有进入源码、报告或Git。

以前“AIUI大模型默认关闭、始终本地Qwen”的判断已被v3真实请求纠正，旧诊断仅为
旧SDK/旧链路结果。本机程序现在不把NLP权限或协议错误当作整机断网。
默认程序及--ros-speech均进入改造总控，不触发原上游小智公网客户端。

本轮验证范围为语音和网络路由，未验证整机导航、驱动、视觉等其他工作空间完整功能。

## 现场无声诊断

已捕获真人`lu4 ka3`硬件唤醒、ASR文字、AIUI回复和TTS播放完成；识别到的
“布卡”“查看”不等于预定测试整句成功。用户两次确认未听见提示音和回复，
因此不升级为现场验收通过。

唯一播放设备为C-Media USB Audio Device。发现PCM音量0%（-37dB），调整为65%
（-13dB）并保存ALSA状态。新AIUI测试PCM有113920字节，RMS约2429、峰值14186，
是有效非静音信号；实际实体扬声器可闻及接线仍待确认。记录见
`~/luka_data/runtime/audio/acceptance/cloud_tts_speaker_check.json`和
`~/luka_data/runtime/xiaozhi/acceptance/human_wake_observation.json`。

现场也观察到AIUI音频请求偶发12秒无结果（错误码0），后续独立合成成功。
保留在线错误不降级规则；新增安全诊断字段，不把此现象归为已解决的网络故障。
服务环境文件已重新对齐`src/common/config/audio.env`，不再引用已移除的legacy目录。
