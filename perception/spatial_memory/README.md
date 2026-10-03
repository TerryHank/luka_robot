# NX 固定相机物体空间记忆

部署目标：`nvidia@192.168.3.251`，目录 `/home/sunrise/luka_ws/perception/spatial_memory`。
用途：持续观察桌面场景，记住物体类别、相机视角位置、有效深度、照片和最后出现时间，并支持中文类别查询。

## 使用

在这台 Windows 电脑的项目目录执行：

```powershell
./spatial_memory/query.ps1 鼠标
./spatial_memory/query.ps1 杯子在哪里
./spatial_memory/query.ps1
```

在 NX 上也可查询（无需联网，服务停止后也可查询历史数据库）：

```bash
cd /home/sunrise/luka_ws/perception/spatial_memory
.venv/bin/python app.py query '鼠标在哪里'
.venv/bin/python app.py query --json
```

局域网只读 API：

- 状态：<http://192.168.3.251:8091/health>
- 当前标注画面：<http://192.168.3.251:8091/snapshot.jpg>
- 记忆查询：<http://192.168.3.251:8091/search?q=鼠标>
- 全部已确认记忆：<http://192.168.3.251:8091/search>
- 单物体照片：查询结果中的 `snapshot` 路径。

调试时镜头调整期间的记录保留在 `commissioning-20260907` 视角，可通过 `/search?q=鼠标&frame=commissioning-20260907` 或 `app.py query '鼠标' --frame commissioning-20260907` 查看。旧视角的位置不能直接当作当前相机视角的位置。

API 只监听板卡局域网地址，未设置公网转发，也未提供远程修改数据库的接口。

## 坐标与记忆含义

- 坐标原点为固定相机的 RGB 光心；x 向右、y 向下、z 向前，单位米。显示的“前方距离”是 z，不是欧氏距离。
- 使用相机出厂内参和 OpenNI 原生深度到彩色对齐。彩色/深度通过主机接收时间近似配对，适用于静态桌面场景，不是硬件同步。
- 坐标是检测框中央表面的深度中位数估计，不是物体精确三维中心；玻璃、反光、遮挡、超出测距范围或混合深度会使测距不可靠。
- 无可靠深度时返回 `xyz_m: null`，保留二维位置；不会把缺失深度当成零米或沿用旧距离。
- 连续多次观测确认后存入可查询记忆。短时间未再检测到的物体保留为历史记录；历史位置并不代表物体现在仍在那里。
- 按类别和相近位置关联记录；同类物体在同一位置被替换时，无法保证身份连续。移动物体可能留下多个位置记录，最近观测排在前面。
- **移动或转动相机后必须新建视角**：停止服务，修改服务 `ExecStart` 添加 `--frame desktop-camera-v2`，再重载启动。旧视角可通过 `app.py query --frame desktop-camera-v1` 查询。地图定位和跨视角变换尚未接入。

## 模型和边界

YOLO11n COCO 检测模型，底层模型覆盖 80 个常见类别。服务默认仅记忆桌面/室内物体，包括杯子、瓶子、鼠标、键盘、手机、书、椅子等；默认忽略人和交通工具，减少背景或屏幕内容进入桌面记忆。`/health` 的 `classes` 字段列出启用的类别及中文名称，`serve --all-classes` 可启用全部类别。
中文查询采用类别/别名匹配，不是大语言模型；暂不支持任意新物体类别、颜色、物主、文字内容或“我的那个杯子”等个体识别。
默认置信度阈值 0.4，每 0.5 秒进行一次检测。TensorRT FP16 使用 NX GPU；ONNX Runtime CPU 后端用于验证与手动备用运行。

官方来源：

- [Ultralytics YOLO11](https://docs.ultralytics.com/models/yolo11/)
- [官方 YOLO11n ONNX 权重](https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11n.onnx)
- [Ultralytics 许可说明](https://www.ultralytics.com/license)
- [Orbbec 官方 OpenNI ARM64 运行库](https://github.com/orbbec/ros2_astra_camera/tree/master/astra_camera/openni2_redist/arm64)
- [Orbbec 官方标定数据结构](https://github.com/orbbec/ros2_astra_camera/blob/master/astra_camera/include/openni2/OniCTypes.h)
- [NVIDIA TensorRT](https://docs.nvidia.com/deeplearning/tensorrt/latest/inference-library/python-api-docs.html)

## 管理

```bash
sudo systemctl status spatial-memory
sudo systemctl stop spatial-memory
sudo systemctl start spatial-memory
sudo systemctl restart spatial-memory
journalctl -u spatial-memory -n 50 --no-pager
```

服务配置为启动后自动采集，数据库在 `data/memory.sqlite3`，物体照片在 `data/objects/`，当前帧在 `data/latest.jpg`。物体最新记录长期保存；每个物体最多每十秒存一条观测历史，观测历史保留 30 天。照片保留每条位置记忆的最新裁剪图，不保存连续录像。应定期检查磁盘容量。

关闭开机启动：`sudo systemctl disable spatial-memory`。

相机被占用时不要同时运行探测程序。相机拔出或采集失败会使进程退出，systemd 重试启动；API 不会将旧帧标为在线。

## 环境和复现

- Jetson Orin NX 16GB，Ubuntu 22.04，L4T 36.4.4，CUDA 12.6。
- NVIDIA 仓库软件包：TensorRT 10.3.0.30 与 `nvidia-l4t-dla-compiler=36.4.4-20250616085344`。
- Python 3.10 独立虚拟环境，启用 system-site-packages 读取系统 TensorRT Python 绑定；Python 依赖见 `requirements.txt`。
- OpenNI ARM64 库在 `sdk/`，模型在 `models/`，下载来源和 SHA256 在 `data/artifact_manifest.json`。
- udev 规则 `/etc/udev/rules.d/70-spatial-memory-orbbec.rules` 只给 video 组访问已识别的 `2bc5:060f` 深度设备的权限。

重新构建 GPU 引擎（只适用于当前板卡/运行库）：

```bash
cd /home/sunrise/luka_ws/perception/spatial_memory
export LD_LIBRARY_PATH=/usr/lib/aarch64-linux-gnu/nvidia:/usr/local/cuda/lib64
.venv/bin/python build_engine.py
.venv/bin/python -m unittest -v test_core
```

应先停止采集服务再重建引擎。TensorRT 引擎不能假定可跨设备或版本复制使用。
