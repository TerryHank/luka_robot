# Luka Moss 接入候选

状态：**BLOCKED_AIUI_TOOL_LOOP / NOT_CUT_OVER**。

已安装并在 S100 构建锁定的 Moss SDK，提供 AIUI v3 结构化文本协议适配、
本地 OpenAI-compatible provider 和网络路由候选。当前没有生产 Agent 服务，
没有删除旧触发规则，没有修改现有小智消费者，也没有发送实车动作。
不得将这些候选文件当成已完成的机器人任务调度系统。

## 安装与开发入口

源代码位于 `~/luka_ws/src/system/luka_agent`，上游提交和源码校验值见 `UPSTREAM.json`。
官方 Node 24.18.0 ARM64 安装在 `~/luka_data/runtime/toolchains`。

```bash
export PATH=~/luka_data/runtime/toolchains/node-v24.18.0-linux-arm64/bin:$PATH
cd ~/luka_ws/src/system/luka_agent
npm run bootstrap
npm run bootstrap:skills
npm test
bash scripts/moss-dev.sh skill list
```

开发入口固定只读，与语音入口分离。它使用独立开发配置和会话，尚未配置开发模型账号；
技能目录可检查，不能宣称已经验证了每项技能在设备上的执行。

RDK Hub 只作为索引并提供 finder/installer，设备技能仅来自 `rdk-device-skills`。
共26个设备技能和2个索引技能，无同名重复；开发技能链接位于
`~/luka_data/runtime/agent-dev/.moss/skills`，没有工作区根目录快捷方式。
厂商源码与 npm 依赖位于被 Git 和 colcon 排除的 vendor，通过锁定清单重建。

## AIUI 门槛与阻塞

官方交互API提供 `parameter.nlp.prompt`，候选适配器用它传递动态工具描述和JSON输出协议。
这不是声称AIUI提供了原生Function Calling接口。模型返回的结构化文字须先通过解析和
运行时工具检查，才交给Moss执行。联网错误不会调用本地Qwen补做。

真实AIUI + 真正Moss SDK的模拟验收未通过：

- 模型曾直接返回“我会……”并结束，没有执行工具。
- 模型曾在查询航点的同一轮，用未经解析的名称提交导航。
- 模型曾猜测尚未返回的导航操作ID；执行器拒绝后未正确修复。
- 缩短提示后可读取真实返回的随机航点ID，但仍出现非法JSON。
- 一次格式修正实验改变了尚未执行的动作，最终候选已移除这种自动修正。

原始模型回答和模拟调用记录在 `~/luka_data/runtime/agent/acceptance`，不含凭据。
测试全程没有真实导航、音乐或底盘执行器。不能通过放宽ID检查、忽略JSON错误、
伪造完成结果或切到其他模型把该门槛变成通过。

后续必须先使当前AIUI接入稳定通过此门槛，再完成业务插件注册、NDJSON Unix socket服务、
ROS客户端切换、旧规则移除、音频协调和全部业务回归。当前保留完整可用语音入口。
本地Qwen候选只完成协议单测，尚未进行本轮真实离线工具循环验收。

## 验证与回退

```bash
# 真实AIUI，但工具全部为模拟；与生产AIUI对话错开运行。
npm run verify:aiui
```

这条命令会调用AIUI并写验收记录，不是普通只读状态命令。
当前预期结果为阻塞，不能用于生产切换。生产服务需先暂停小智对话消费者，
测试结束后恢复；不要同时运行两个使用同一AIUI设备会话的消费者。

迁移前归档：`~/luka_data/backups/before_moss_20261008_192213/source_config.tgz`。
SHA256：`7df89b910f376a88901dec1af105af71d03222aa2bd79067d5f461b5791ff7fe`。
归档包含私有配置，权限600、父目录700，不得上传Git。

仅新增候选目录、工具链和开发技能目录；生产代码尚未切换，因此当前无需回退生产代码。
