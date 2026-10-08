# Astra Pro Plus 安装、替换与话题验收

2026-10-03；目标 sunrise@192.168.3.150，Ubuntu 22.04.5，aarch64。

已在新工作区启用 Orbbec ROS2 驱动，并将视觉来源由单目/旧双目 UVC 切换到 Orbbec ROS RGB-D。原 `/home/sunrise/luka_s100` 未修改；8183 个复制源文件哈希复核变化为 0，12 个旧服务定义变化为 0。Odin 保持排除。

## 安装内容

- Orbbec SDK v1.10.37 官方 Linux ARM64 ZIP；发布资产当前没有所引用的 `OrbbecSDK_v1.10.37_arm64.deb`。独立下载包、示例及文档现归档于 `/home/sunrise/orbbec_sdk_v1/OrbbecSDK_v1.10.37`（2026-10-07 从工作区移出），Unix 库软链接已保留。
- ROS 驱动版本 1.5.21，位于 `sensing/OrbbecSDK_ROS2`。已移出其 COLCON_IGNORE 并构建 `orbbec_camera`、`orbbec_camera_msgs`、`orbbec_description`，当前共13个ROS包；驱动使用的核心库与官方下载库 SHA256 一致。
- 新增 ROS 依赖 backward_ros、camera_info_manager、camera_calibration_parsers、image_publisher；没有全量升级系统。
- USB 规则 `/etc/udev/rules.d/99-luka-orbbec-astra.rules` 仅匹配 2bc5:060f 与 2bc5:050f，权限0660、video组；sunrise已在video组。
- 设备自报 Astra Pro Plus、固件 RD2513；未更改设备固件。

官方来源：[Release v1.10.37](https://github.com/orbbec/OrbbecSDK/releases/tag/v1.10.37)，[发布资产清单](https://api.github.com/repos/orbbec/OrbbecSDK/releases/tags/v1.10.37)，[v1设备兼容表](https://github.com/orbbec/OrbbecSDK/blob/v1.10.37/README.md)。Astra Pro Plus 在 v1 为有限维护，在 v2 不支持。

下载 ZIP SHA256：`3c269b7eac354dbb69a6d4519cc587b21b6390baaacce7ce79331593c97489a0`。

## 当前 SDK 目录布局（2026-10-07）

工作区中的相机集成为 `sensing/OrbbecSDK_ROS2`，保留 `orbbec_camera`、
`orbbec_camera_msgs` 和 `orbbec_description`。驱动从自身的
`orbbec_camera/SDK/include` 和 `orbbec_camera/SDK/lib/arm64` 构建，
运行时使用 `install/orbbec_camera/lib` 内的 SDK 库。
这些库与独立 v1.10.37 SDK 的核心库哈希一致。

独立 `orbbec_sdk_v1` 已移至 `/home/sunrise/orbbec_sdk_v1`；
相机服务、构建脚本及库加载路径均无需依赖该归档位置。
USB 规则源文件保存在 `system/udev/99-luka-orbbec-astra.rules`，已作为独立文件安装到 `/etc/udev/rules.d/99-luka-orbbec-astra.rules`。
`system/scripts/start_orbbec_camera.sh` 继续使用 `ros2 launch orbbec_camera astra_pro_plus.launch.py`。

## 实际话题接收

启用640×480、30fps RGB/深度，关闭IR与点云；SDK软件D2C配准 `depth_registration=true, align_mode=SW`，启用深度尺度转换。

| 话题 | 15秒接收量 | 实测频率 | 数据 |
|---|---:|---:|---|
| `/camera/color/image_raw` | 450 | 29.99 Hz | 640×480，rgb8 |
| `/camera/depth/image_raw` | 450 | 30.00 Hz | 640×480，16UC1 |
| `/camera/color/camera_info` | 450 | 30.00 Hz | 640×480，CameraInfo |
| `/camera/depth/camera_info` | 451 | 29.99 Hz | 640×480，CameraInfo |

RGB与配准深度的frame_id均为 `camera_color_optical_frame`，两路CameraInfo内参一致。深度单位为毫米，16UC1中的0为无效深度。
采样有效深度比例约 65.1%，有效像素中位深度约 2.457 米；这是现场采样，不是测距精度或标定验收。

图像初次接收时存在丢帧/过期，原socket缓冲上限为212992字节。已设置 `/etc/sysctl.d/60-luka-orbbec.conf` 的rmem_max、wmem_max为16777216，并仅在新工作区的 `common/config/cyclonedds_offline.xml` 添加16MB收发缓冲。旧工作区配置未改。调整后上述四个话题均约30Hz。依据：[CycloneDDS大样本接收说明](https://cyclonedds.io/content/faq.html)。

## 上层功能接入

- 新增 `perception/spatial_memory/orbbec_ros_camera.py`，订阅已配准图像及工厂CameraInfo，不重复打开USB。拒绝不匹配坐标系、尺寸、内参、格式及过期/不同步数据；三个适配测试通过。
- `luka-ws-vision.service` 默认 `NX_CAMERA_SOURCE=orbbec_ros`，依赖 `luka-ws-orbbec-camera.service`，不使用旧双目标定。
- 人员模块继续使用共享帧接口，取得真实深度和工厂内参；`metric_depth_available=true`、约8fps、`motion_enabled=false`。接口中stereo_shared表示历史共享传输模式，不表示物理相机为双目。
- 预览、普通快照、兼容高清快照均HTTP200。当前实际RGB是640×480，高清接口不会创造更高分辨率。
- BPU实际帧检测通过；YOLOE从640×480实际帧完成推理。深度投影检查得到有限相机坐标；没有声称机器人地图坐标或跟随精度已验收。
- 相机到车体的安装外参仍需按实际安装位置核实；未执行导航、巡航或跟随移动测试。

## 启动与检查

当前新工作区静态模式8个服务运行，相机话题持续发布。底盘、导航、boot-localize和旧工作区服务均inactive；未启用相机开机启动。

仅启动相机：

```bash
source /home/sunrise/luka_ws/src/system/environment.bash
sudo systemctl start luka-ws-orbbec-camera.service
ros2 topic list | grep /camera/
# 下列hz检查分别运行，Ctrl+C结束
ros2 topic hz /camera/color/image_raw
ros2 topic hz /camera/depth/image_raw
```

启动相机和页面/静态视觉；停止新工作区：

```bash
/home/sunrise/luka_ws/src/system/luka.sh start ws stationary
/home/sunrise/luka_ws/src/system/luka.sh stop ws
```

启动/停止脚本已包含新相机服务并通过实际停启验证。网页 `http://192.168.3.150:8503/`。stationary不自动启动底盘；原页面中的硬件启动操作仍存在。full模式仍可能自动旋转定位，本次未执行。旧工作区仍按原相机配置启动。

```bash
journalctl -u luka-ws-orbbec-camera -u luka-ws-vision -n 80 --no-pager
```

备份：`/home/sunrise/luka_migration_backups/orbbec_20261003`，含原驱动SDK、COLCON_IGNORE、视觉服务/启动脚本/应用、DDS配置和原socket缓冲值。验收JSON及构建日志：`/home/sunrise/luka_ws/src/evaluator/orbbec_20261003`。
