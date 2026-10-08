# NX 硬件静态验收 2026-09-10

NX 重启后仍为 192.168.3.251。未启动底盘控制节点、导航或运动任务。

## 串口修复与验证

内核 5.15.148-tegra 原本没有 CH341 驱动。使用 Linux 官方 v5.15 drivers/usb/serial/ch341.c，针对本机内核头文件和 Module.symvers 编译，安装到 /lib/modules/5.15.148-tegra/updates/ch341.ko 并执行 depmod。驱动与当前内核绑定，升级内核后需要重新编译。

BRLTTY 错误抢占 FTDI 与 CH340，内核日志明确出现 claimed by ... while brltty sets config。增加 /etc/udev/rules.d/85-brltty.rules 排除机器人设备；仍发生 brltty-udev.service 抢占，因此 mask 该服务并停止进程。USB 复位后两个 CH340 均恢复。以后若要使用盲文设备，需要先处理这个冲突再解除 mask。

99-nx-robot-serial.rules 增加 /dev/nx_base（FTDI 序列号 UCBEA075）和 /dev/nx_imu（USB 物理路径 1-2.4.3）。IMU 插到其他 Hub 端口时必须重新确认绑定。两个 CH340 没有唯一序列号，原 by-id 名称冲突，不可用它区分 IMU。nvidia 已加入 dialout。

IMU 921600 波特率两秒收到 8005 个校验通过的 WIT 帧，类型 0x51/52/53/54。另一 CH340 用途未确认，未写配置。

底盘仅调用原协议库的读取位置/速度函数，free 协议、x 固件格式、115200 波特率；四个电机地址 1–4 都有效回复，测试时位置/速度均为 0。没有调用速度设置、使能、同步或停车控制函数。证据 nx_motor_readonly.json。

## 双雷达

- enP8p1s0：A48FECF0C3E09ED4A0EA98F337574116，健康 OK，收到 225 帧，3240 点/帧，约 10 Hz。
- enx00e04c68059e：B4CAFA86C2E392D0A5E59FF7231E5C60，健康 OK，收到 213 帧，3240 点/帧，约 10 Hz。

验证时通过各自绑定网卡的 UDP 代理连接，两台雷达都是 192.168.11.2:8089。结束后测试节点退出。后续持久连接 nx-lidar-native 使用 192.168.11.10/24，nx-lidar-usb 使用 192.168.11.11/24，never-default，不修改 Wi-Fi 默认路由。地址更新后两个网口均 ping 成功。

上下层身份还需要用户核对。未把未经确认的外参接入定位或避障。test_lidars.py 已更新为最终源地址。

## 音频与网页

稳定 ALSA 名称：麦克风 plughw:CARD=XFMDPV0018,DEV=0；扬声器 plughw:CARD=Device,DEV=0。3 秒 16 kHz 单声道录音成功，中文测试音频播放命令成功退出；没有把这项当作真人识别准确率或主观听感验收。未启动常驻录音。

nx-agent/nx-dashboard 已重新启动，依然是隔离域 87、dry_run。配置 /home/sunrise/luka_ws/common/config/nx_hardware.env 已保存。本轮测试均不驱动车轮。

下一步：先核对双雷达上下位置与外参，做真实传感器静态定位，再安排停车联锁与低速实车测试。

## 用户确认上下层后的联调

用户确认自带网口为上层，因此 enP8p1s0=上层、enx00e04c68059e=下层。nx_sensors.launch.py 已按此映射使用原车外参：上层 base_link→laser=(-0.065,0,0.42, yaw=0)；下层 base_link→laser_low=(0.281,0.005,0.10, yaw=1.56975)，下层 inverted=true。保持原车安装不变的前提下使用这些参数，并非重新标定结果。

nx-sensors 服务已启动（未设开机自启），只含双雷达 UDP 代理、雷达节点、IMU、固定外参和扫描融合。修复了雷达启动早于 UDP 代理就绪导致首次握手超时的问题。

8 秒实测：上层 82 帧、下层 81 帧、下层过滤 81 帧、融合 31 帧，均为3240点。IMU 本次复测失败：先 USB 控制传输超时，设备复位后 USB 物理路径 1-2.4.3 已从系统消失，/dev/nx_imu 不存在，不能继续沿用上轮短时成功作为当前健康状态。其他设备仍在。等待检查/重新插拔 IMU USB 线，节点保留自动重连。

尚未启动真实地图定位，未生成任何假位姿或行驶指令。证据 nx_sensors_live.json。

## 换口恢复与四楼厨房静态定位

用户换口后 IMU 在 1-2.1 重新枚举，收到校验通过的 WIT 数据；已将 /dev/nx_imu 的 udev 规则改绑该口并备份旧规则。45 秒 ROS 连续采样收到 4501 条 IMU 消息（100.02 Hz），最大到达间隔 0.0136 秒；上下雷达分别450/449帧，融合165帧。换口后这段验证未见掉线，但不代表已完成长时间可靠性验收。

用户确认小车在四楼厨房附近。nx-localization 服务仅启动读编码器的独立里程计、地图、AMCL 和生命周期管理器，不含导航控制器或电机控制节点。只读总线允许 free 协议 0x36 位置读取，禁用控制写入。里程计来自真实编码器，原点为启动时的局部里程计原点；未发布伪造固定 odom→base_link。

初值取正式 semantic/floor_4/pois.yaml 中 wp_008 厨房（不是 nav_llm_agent 的占位航点），位置标准差1.5m、航向宽分布。静止下请求约30次无运动激光更新，得到候选 x=-1.1424m、y=-0.3006m、yaw=0.1935rad。3088个有效激光终点中约59.7%落在地图障碍物15cm内，中位终点距离10cm；这不是定位绝对误差。AMCL协方差因静止重复采样塌缩到接近零，不能解释为极高精度。结果只作为待核对的静态估计，不允许据此自动行驶。

网页横幅已改为静态定位估计待核对。新服务均未设置开机自动启动；底盘运动入口仍关闭。证据 nx_localization_check.json 和更新后的 nx_sensors_live.json。
