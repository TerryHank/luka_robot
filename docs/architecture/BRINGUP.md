# Canonical 启动入口

source /home/sunrise/luka_ws/system/environment.bash 后执行：

```sh
ros2 launch luka_bringup robot.launch.py
```

默认启动硬件、双雷达、AMCL、安全链、Nav2 和一个 Behavior/Mission/API composition host。所有行为默认停止，定位仍须现有地图核验和显式初始化，不自动旋转。需要模型和音频时可明确设置 enable_perception:=true、enable_agent:=true、enable_voice:=true；原音频设备环境变量与模型路径要求保留。

hardware → sensing → localization → perception → motion_safety → navigation → Behavior/Mission host → interaction 按顺序提交启动。TimerAction 是启动顺序，不代表组件已经就绪；服务、lease、定位、目标和新鲜度门仍决定是否允许动作。

MissionManager 和 BehaviorRegistry 共用一个 host，mission.launch.py 包含 behavior.launch.py；robot.launch.py 不另起第二个 host。硬件仅有一个 Base Gate/driver owner，canonical localization 不另起只读串口节点。

原 system/bringup/start_nx_*.sh 均保留；nx_navigation.launch.py 是兼容 wrapper，调用 canonical navigation/safety actions。上游已删去根目录快捷链接，不恢复它们。workspace_root 用于显式选择源码/配置根，隔离构建可指向候选目录。

运行总入口前停止重叠的旧 systemd 硬件/导航/API 服务；禁止同时运行两套串口、topic 或任务 owner。安装后通过 ros2 launch luka_bringup robot.launch.py --show-args 校验配置和包加载，再做现场完整启动验收。
