# 20 VI-1 声源方位与语音导航

合同对应状态：**部分完成**

DOA/语音路由/Agent有代码；当前DOA记录不能代替新鲜实时检测；声源趋近完整联动未验收。需要有效NX_MIC/NX_SPEAKER配置。

## 启动及观察

    cd "/home/sunrise/luka_ws/src/examples/contract_demo/20_VI_1_声源方位与语音导航_部分完成"
    ./demo.sh

启动现有语音网关、本地LLM、Agent和页面；显示DOA、语音状态、识别命令和Agent状态。需要有效音频设备/模型，实际语音命令可能经现有门控请求导航。

- ./check.sh：查看launch参数，不启动设备。
- ./demo.sh start_hardware:=false：仅回放/隔离监视，不能作为硬件验收。
- Ctrl+C 或另一个终端 ./stop.sh：停止本launch创建的进程，保留复用的运行服务。
- 按序演示时先结束上一项。完整已有栈可以复用；部分栈/重复串口/SLAM-AMCL冲突会拒绝启动。
- Foxglove连接 ws://192.168.3.150:8765。页面 http://192.168.3.150:8503/。
- 空闲状态、无目标、缺设备时如实显示WAITING；STALE/INVALID不是验收通过。
- 本次验证不发送实车运动目标；真实运动/避障/返航效果仍需现场验收。

## 代码证据

- /home/sunrise/luka_ws/src/visualization/console/nx_xfm_doa.py
- /home/sunrise/luka_ws/src/visualization/console/nx_voice_gateway.py
- /home/sunrise/luka_ws/src/system/bringup/start_nx_voice.sh

## 本地语音链路（2026-10-08）

现有 voice 服务入口已接入 `src/system/luka_audio`：音频板硬件唤醒与 DOA，
RDK SenseVoice 本地识别，RDK WeTTS 本地合成；AIUI 暂未启用。
当前固件唤醒词日志为 `lu4 ka3`（露卡），说唤醒词后说测试句。
观察 `/voice/hardware_wake`、`/voice/doa`、`/voice/recognized_text`、`/voice/status`。
`/voice/tts_text`（std_msgs/String）可测试本地播报。
本轮 `LUKA_VOICE_DISPATCH_COMMANDS=false`，不自动导航或趋近；合同状态仍为部分完成。
详见 `src/system/luka_audio/README.md` 和 `ACCEPTANCE.md`。

## 语音智能体升级

当前联网识别/合成使用AIUI，离线回退RDK；新增S100本地小智会话总控和本地Qwen模型。
`luka-ws-xiaozhi.service` 接收识别文字并返回回答，已通过无公网进程回放及实际播放测试。
供应商ARM库默认关闭NLP，现由S100本地Qwen负责对话；AIUI联网识别和合成正常；动作下发保持关闭，声源趋近未验收。
小智服务与voice共享一套采集/播放；详细结果见src/system/luka_xiaozhi/ACCEPTANCE.md。

## 最终AIUI联网路由

当前规则为联网全部使用AIUI识别、v3个性化大模型回复和合成；只有确认公网不可达才调用
本地SenseVoice/Qwen/WeTTS。联网认证、权限和服务错误不会自动切本地。
云对话已真实通过，先前“始终本地Qwen/需等待定制库”的说明属于历史阶段。
声源趋近与自动导航仍未验收，动作许可仍关闭，合同目录状态继续保留部分完成。
最新启动说明与证据见src/system/luka_xiaozhi/README.md、ACCEPTANCE.md。
