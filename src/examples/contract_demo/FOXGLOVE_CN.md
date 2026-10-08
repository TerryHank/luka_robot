# Luka 原生 Foxglove 操作与合同验收

Windows客户端：1.86.0-cn.13；机器人数据直连 `ws://192.168.3.150:8765`。
所有交互使用Foxglove的原生面板、React/MUI控件和ROS bridge，不加载旧网页或iframe，不启动dashboard服务。

## 一键启动

```powershell
$demoScript="D:\Workspace\foxglove-studio-cn\integrations\luka-contract-demo\start_demo.ps1"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File $demoScript -Item 01 -Run
```

`-Run`包含SSH启动对应远端ROS launch；省略时只连接和选择布局。其他案例替换编号。
客户端右侧“原生控制”用于操作，“本案例步骤”显示该项观察、证据与缺口。
01/02共用底盘场景。25项教程见[验收手册](acceptance/ACCEPTANCE_GUIDE.md)，26/27为交付与服务附录。

## 原生交互

- 方向：收到新鲜底盘状态、编码器及双雷达后勾选“启用本次方向操作”；按住六个方向按钮。松开、失焦、取消指针、切换布局或数据过期停止。单次最长2秒，线速度0.10m/s、角速度0.20rad/s。机器人仍执行已有0.3秒指令超时、传感器新鲜度和碰撞门控。
- 定位：3D发布位姿估计工具向`/initialpose`发送初始位姿；操作者核验扫描与地图重合。原网页自动重定位流程未接入本面板。
- 单点导航：3D发布位姿到`/contract_demo/goal_pose`，只暂存30秒；点击“执行暂存导航目标”，经`/nx/navigation_enable`安全门后调用现有Nav2 `NavigateToPose`。读取`/contract_demo/navigation_status`的反馈和结果；取消后确认实测停止。
- 巡检14：3D设置发布位姿话题为`/patrol/add_pose`添加多个点；原生按钮保存/读回路线、巡航一圈、暂停/恢复、停止。停留时间按现有路线YAML配置。路线存储在`luka_data/recordings/contract_demo/business/demo_route.yaml`，保存会更新本演示文件。
- Home17：记录当前位置、软件返航、取消；只演示软件Home，不能代替精准对接/自动充电。
- 地图09/10：09建图时点击保存，服务先返回已接受，随后在`/contract_demo/map_status`核对完整导出结果及新路径；现有导出器使用唯一文件名，不覆盖生产地图。停止SLAM及现有地图节点，再用10 `-MapYaml /home/sunrise/luka_data/maps/contract_demo/保存目录/map.yaml -Run`重载。
- 状态机24：原生暂停、恢复、取消任务服务；结合任务状态与实测里程计检查效果。独立导航示例不自动变成mission任务，mission状态联动需由现有任务入口创建相应任务。
- 语音20：原生文字播报；实际唤醒/识别使用麦克风，观察原生RawMessages。文字播报不能证明实时DOA或声源趋近。
- IMU03：默认原始六轴；先有轮里程计，再03 `-WithEkf -Run`验证融合。

旧`/nx/web_teleop_cmd_vel`和`/nx/web_teleop_status`名称保留为受保护ROS接口兼容名；不依赖网页服务。MCP只有布局、连接、截图工具，不替操作者点击运动按钮。

## 停止与验收

松开方向键只停止当前手动输入；活动导航用取消按钮。结束用Ctrl+C或对应stop.sh；不把关闭Foxglove当作所有任务停止。
01与09/04组合时先01后算法，结束先算法后01；SLAM与AMCL互斥。
[现场记录模板](acceptance/acceptance_record_template.csv)初始均为“未验收”。缺固件/CAN、车型差异、回充/烟雾/权限联动等项如实标记，按钮不代表合同整项完成。

[原生组件清单及官方参考](NATIVE_COMPONENTS.md)

## 开发验证

- `node --test integrations/luka-contract-demo/test_native_control.cjs`：5项方向控制模拟回归。
- 远端命令及现有launch/runner回归54项；ROS域188的模拟Nav2/安全门传输回归1项。
- TypeScript、web打包、Windows打包与实际窗口读回单独验证。
- 本次测试没有向实车发送速度或目标；合同现场验收按25项手册执行。

源文件`ros/native_commands.py`部署至远端`src/examples/contract_demo/_shared/`，由示例launch启动，是现有Nav2和地图导出器的命令适配层，不新增运动控制器。
