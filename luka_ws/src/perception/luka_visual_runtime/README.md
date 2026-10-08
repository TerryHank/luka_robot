# Luka 当前视觉共享服务

一键入口：`src/system/scripts/start_orbbec_vision.sh`；部署服务：`luka-ws-vision.service`。
页面端口沿用 8091。当前仅订阅已注册的 Orbbec ROS RGB-D，不重复打开 USB 相机。

- `live_app.py`：图像预览、拍照、连续识别和现有 HTTP 接口。
- `patrol.py`：录像、关键帧及录像检索。
- `object_memory.py`、`semantic_memory.py`、`semantic_store.py`：现有对象和语义记忆。
- `orbbec_ros_camera.py`、`rgbd_geometry.py`：时间戳匹配、注册深度与几何计算。
- 图片推理由 `luka_image_inference` 提供，当前 BPU 模型只支持 person；不支持任意物体、描述和颜色查询。

数据继续位于 `~/luka_data/recordings/locateanything_trial_20260907`，历史文件不改名、不删除。
旧 NX/TensorRT、原生相机和旧空间记忆应用已移到工作区外归档。
本服务不发布运动指令；无人阶段仅验证模拟输入和 HTTP 服务启动。
