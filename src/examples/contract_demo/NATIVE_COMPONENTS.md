# Foxglove 原生组件盘点

核对时间：2026-10-08。已使用AnySearch检索官方文档，并检查本地源码及GitHub仓库。

## 可直接组合的组件

|功能|本地已有面板|合同示例用途|
|---|---|---|
|地图/模型/雷达/路径与发位姿|3D|04、08–15、17|
|RGB/深度/人脸结果|Image|05、22|
|IMU/里程计/速度曲线|Plot|01–03、15|
|测量与接口字段|RawMessages、Table|01–07、20、24、25|
|方向控制|Teleop|01/02；本地旧实现需补齐松开停车；本轮Luka原生面板已提供六方向与时效门控|
|消息按钮|Publish|TTS、Home、巡检等已有话题；运动入口须保留现有安全门|
|服务按钮及返回值|CallService|地图保存、任务暂停/恢复/取消、保护底盘服务|
|健康/故障|DiagnosticStatusPanel、DiagnosticSummary、RosOut|25；需真实诊断消息，不能空面板当自检成功|
|状态灯/仪表/状态时间线|Indicator、Gauge、StateTransitions|20、24、25|
|ROS拓扑与来源|TopicGraph、SourceInfo|06–08、25|
|地图经纬度|map|地理坐标数据；室内OccupancyGrid使用3D面板|
|参数/变量/页面组织|Parameters、GlobalVariableSliderPanel、Tab|参数检查及演示布局；方向面板速度不开放任意变量放大|
|本轮原生定制|LukaConsole|人手方向操作、ROS服务/消息按钮、本地27条验收说明|

本地原有20种面板，本轮新增LukaConsole后21种。清单来自`packages/studio-base/src/panels/index.ts`；不把官方文档新增的Audio、Markdown、Transform Tree等视为本地已实现独立面板。

## 官方文档与源码的边界

- [官方面板目录](https://docs.foxglove.dev/docs/visualization/panels)
- [Teleop](https://docs.foxglove.dev/docs/visualization/panels/teleop)：支持Twist、配置方向字段/频率；最新文档已有Stop on release。本地fork尚没有该配置。
- [Publish](https://docs.foxglove.dev/docs/visualization/panels/publish)：编辑JSON或仅显示发布按钮，需要支持发布的连接。
- [Service Call](https://docs.foxglove.dev/docs/visualization/panels/service-call)：服务请求/响应、按钮和超时等配置；本地旧版配置不完全相同。
- [3D](https://docs.foxglove.dev/docs/visualization/panels/3d)：地图、模型、TF、扫描和位姿工具；本轮保留已有实现。
- [自定义扩展](https://docs.foxglove.dev/docs/extensions)：原生面板可订阅、发布并呈现交互；官方客户端安装本地扩展需要developer seat。
- [扩展注册API](https://docs.foxglove.dev/docs/extensions/extension-api/interfaces/ExtensionContext)：registerPanel与initPanel注册自定义原生面板。
- [你的面板目录](https://github.com/TerryHank/foxglove-studio-cn/blob/main/packages/studio-base/src/panels/index.ts)
- [你的源码许可证](https://github.com/TerryHank/foxglove-studio-cn/blob/main/LICENSE)：MPL-2.0；复用、修改和分发须遵守许可证。MUI Material本地依赖为MIT。
- [官方版本说明](https://foxglove.dev/blog/foxglove-vs-foxglove-studio-two-years-on)：最后开源版本为2024年的1.87.0。最新商业客户端的能力说明不能当作其实现源码可直接搬入fork。

## 本轮实现方式

LukaConsole通过Foxglove PanelExtensionAdapter和PanelExtensionContext接入，使用React/MUI原生面板控件与ROS bridge。没有iframe、外部网页地址或网页HTTP操作接口。

当前客户端内置该面板，不需要购买官方席位安装本轮功能。MCP负责连接/布局/截图，没有机器人运动调用工具。

已有测量面板优先复用；需要明确安全门、六方向、暂存目标确认与合同步骤的部分才使用本轮定制控件。原生导航适配仍调用现有Nav2，不建立第二套底盘控制器。
