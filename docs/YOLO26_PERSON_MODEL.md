> 2026-10-04 更新：人物分割已切换到 S100 BPU HBM。当前部署与验收见 [YOLO26_BPU_DEPLOYMENT.md](YOLO26_BPU_DEPLOYMENT.md)；下文保留此前 CPU 阶段记录。

# YOLO26 人体模型切换与静态验收

2026-10-04，目标 sunrise@192.168.3.150。

仅修改 `/home/sunrise/luka_ws`，旧 `/home/sunrise/luka_s100` 未修改。

模型来源 `/home/sunrise/yolo26m-objv1-seg.pt`，实际为实例分割模型，365 类，person 编号 0。原文件与新工作区中的模型副本 SHA256 均为 `ea190cec15d1425fc695ae6f8b911c55ccf0268a4f48d36fd9422b334f2192a2`。

人体监控、目标 API（8096）、实时检索（8099）均切换至该模型，仅启用 person。人体身份、人脸、BPU 姿态和深度处理保留；当前仅监控，没有运动输出。通用目标查询暂不支持其他类别。

由于 S100 BPU 不能直接执行 PT，使用该 PT 导出的 ONNX CPU 模型，保留源权重、不重新训练。运行输入为 256×256，摄像头图像仍为640×480，检测框及掩膜映射回原图。640 输入 PyTorch 实测约2.3秒/帧，320输入约1秒/帧；256 ONNX实际推理约0.6秒，人体监控约1.7帧/秒。较低输入分辨率可能影响远处小人体识别；未完成远近、遮挡与多人准确率评估。

验证：

- Ultralytics 自带 bus.jpg 正向测试：4个人体，均有非空分割掩膜；8096的全部类别请求仅返回这4个人体。
- 8096请求 chair 返回HTTP422，8099类别表仅person。
- 人体监控连续12次采样无错误，requested=yolo26_seg，motion_enabled=false，真实深度可用。
- 实时检索使用Astra现场画面完成3帧，推理0.621秒，无错误；该次现场未检出人体。正向人体识别证据来自测试图，不将空场景结果当作识别准确率验证。
- 8个新工作区静态服务运行；底盘、导航、旧工作区服务未启动。

依赖安装在独立 `/home/sunrise/luka_ws/perception/person_follow/yolo26_venv`：torch2.6.0 CPU、torchvision0.21.0、ultralytics8.4.172、onnx1.17.0、onnxruntime。源模型副本及导出位于新工作区 `perception/person_follow/models/`。

变更备份：`/home/sunrise/luka_migration_backups/yolo26_person_20261004`。
远端验收数据：`/home/sunrise/luka_ws/evaluator/yolo26_person_20261003/acceptance.json`、`live_acceptance.json`。

静态启动/停止：

```bash
/home/sunrise/luka_ws/system/luka.sh start ws stationary
/home/sunrise/luka_ws/system/luka.sh stop ws
```

网页入口：<http://192.168.3.150:8503/>。
