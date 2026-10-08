# S100 官方 OELLM 语音后端候选

状态：PASS_BUILD / PASS_BPU_RUNTIME / PASS_RECORDED_OFFLINE_CHAIN。真人断网麦克风和扬声器整轮尚未验收。

## 选择

- 板卡实测：RDK S100 V1P1，ADC board ID 0x6A87，Nash-e，12 GB。
- 用户选择整机稳定优先，候选为官方 Qwen2.5-1.5B-Instruct，W8 HBM，1024-token 编译上下文。
- SDK：D-Robotics LLM S100 1.0.0，板端独立运行库，不覆盖系统 DNN/UCP 库。
- HTTP 服务：D-Robotics/oellm_server，固定提交 7fa0ebe04ae0dbde379a7cb3d4c44ea7e0a73db0。
- 官方未提供统一智能排名；不把参数量、生成速度或单项数学成绩当成综合智能排名。

## 路径和接口

- 模型：`~/luka_data/ml_models/oellm/Qwen2.5_1.5B_Instruct_1024.hbm`。
- SDK：`~/luka_data/runtime/oellm/sdk-1.0.0/D-Robotics_LLM_S100_1.0.0_SDK/oellm_runtime`。
- 源码：`~/luka_ws/src/system/luka_xiaozhi/oellm_server`。
- 启动脚本：`~/luka_ws/src/system/luka_xiaozhi/scripts/start_oellm.sh`。
- 拟复用 `luka-ws-chat.service` 和 `127.0.0.1:8092`，模型别名 `qwen2.5-1.5b-instruct-bpu`。
- 健康及调用接口：`/health`、`/v1/models`、`/v1/chat/completions`。
- 联网仍用 AIUI；仅确认断网才调用本地模型。语音动作下发保持关闭。

## 当前证据

- 模型官方 MD5：488cf8fe4bb7c9bd784edf1d86063345，已核对下载文件。
- 官方 server ctypes 结构体大小和关键偏移与 SDK C 头文件在本机一致。
- 23 项既有 Python 测试、模拟 HTTP 调用、旧模型别名拒绝检查通过。
- 7B 文件曾通过官方 MD5，但受限初始化失败：SDK要求一次分配7928646448字节BPU内存。
- 7B候选已在选择较小模型后删除。
- 源码及colcon构建完成；启动设备树与生产本地后端配置已切换，用户已授权重启并完成实测。

## 内存门槛

当前 carveout 512 MiB 不足以加载新模型。已准备独立 DTB 候选，只把 carveout 改为2.25 GiB，
保留现有1 GiB ion_reserved和512 MiB ion_cma；已检查保留区无重叠。
启动脚本检测实际生效 carveout，低于2 GiB时直接拒绝加载。
重启后已确认carveout=2.25 GiB、Linux总内存约7.6 GiB；真实模型加载、中文两轮问答和隔离断网三轮链路通过。

## 接口边界

官方原始示例的平铺消息未通过姓名记忆；适配为完整Qwen ChatML和SDK透传模板后，真实多轮姓名记忆通过。
此官方server没有实现逐请求的max_tokens和动态采样更新，本适配固定temperature=0.3、
上下文1024。现有客户端64-token字段不能视为SDK已执行的生成硬限制。
本地HTTP取消仍沿用丢弃过期回复，不强制停止共享SDK句柄；语音播放取消由原网关处理。
尚未验收工具调用、并发压力或长时间稳定性。

## 官方资料

- https://github.com/D-Robotics/oellm_server
- https://developer.d-robotics.cc/rdk_s_doc/Advanced_development/toolchain_development/LLM_Toolchain/s100_LLM_Toolchain
- https://developer.d-robotics.cc/rdk_s_doc/en/Advanced_development/linux_development/driver_development_super/driver_hbmem/s100_hbmem_hardware

## 本机验收结果

26项Python测试通过（含新增3项OELLM接口回归）。真实SDK初始化、推理、释放返回码均为0。
隔离断公网测试：SenseVoice识别录制音频→新OELLM对话→WeTTS合成，三轮10.97、4.30、4.30秒，llm_command计数0。
测试结束后luka-ws-chat.service为inactive，carveout使用量回落3 MiB，模型按断网请求加载。
联网AIUI路由保持auto。证据在luka_data/runtime/oellm/native_smoke.json、http_acceptance.json、activation.json
以及luka_data/runtime/xiaozhi/acceptance/offline_chain.json。此证据不代替真人离线唤醒或整机所有功能验收。
