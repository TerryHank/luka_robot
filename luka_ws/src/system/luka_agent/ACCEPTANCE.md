# 2026-10-08 Moss 迁移状态

| 项目 | 结果 | 范围 |
| --- | --- | --- |
| 迁移前归档与校验 | PASS | 工作区外归档，代码、配置、服务版本可追溯 |
| 官方Node ARM64 | PASS | 24.18.0，官方SHA256匹配 |
| 固定Moss SDK构建 | PASS_BUILD | e0f163d8fa18dd8913854d6ccb6acbd0e084d15c；Windows与S100构建完成 |
| Moss原生嵌入示例 | PASS_SDK_MOCK | S100执行官方headless-run示例，脚本模型调用status并消费结果；不代表真实AIUI通过 |
| 协议与路由单测 | PASS_UNIT | 8项；动态工具、非法响应、二进制帧、工具结果回传、在线禁止降级、未知网络与离线准备 |
| RDK技能目录 | PASS_CATALOG | 26设备技能＋2索引技能，Moss CLI实际列出28项；设备技能只加载一个来源 |
| 真实AIUI工具循环 | FAIL_GATE | 口头承诺、错误ID、非法JSON、未正确消费执行失败；没有通过多步骤验收 |
| 真实本地Qwen工具循环 | PENDING | provider候选存在，未做本轮真实循环验收 |
| 新Agent服务与ROS切换 | NOT_DEPLOYED | 受AIUI前置门槛阻塞 |
| 固定话术与旧工具规则删除 | NOT_STARTED | 按批准计划，AIUI门槛通过后才删除 |
| 音乐、导航、视觉等业务恢复 | PENDING | 本轮未连接生产执行器，不能报业务恢复成功 |
| 实车运动 | NOT_SENT | 真实AIUI测试仅调用内存模拟器 |

开发Skills安装不代表技能已获执行许可或通过硬件验收。Moss版本号不代表全部上游
测试已通过；本轮仅主张自己的构建、协议测试和明确列出的运行证据。
