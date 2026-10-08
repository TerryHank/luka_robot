# YOLO26m objv1 分割模型：S100 BPU 部署验收

2026-10-04 已完成：指定 PT → BPU ONNX → PTQ 量化 → HBM → S100 原生 BPU 推理 → luka_ws 服务接入。

## 模型与构建

- 源模型：`/home/sunrise/yolo26m-objv1-seg.pt`，源文件未修改。
- PT SHA-256：`ea190cec15d1425fc695ae6f8b911c55ccf0268a4f48d36fd9422b334f2192a2`。
- HBM：`/home/sunrise/luka_ws/perception/person_follow/models/bpu_yolo26/yolo26m_objv1_seg_bpu_nashe_640x640_nv12.hbm`。
- HBM SHA-256：`c4a47cf043abaca891a947fe10d250f1699041fc669eea8b4aa8603cddf0e144`；41,422,816 字节。
- 编译环境：本机 Ubuntu-22.04 WSL，x86_64，uv 0.12.22 创建和管理 `.venv`，Python 3.10.12。没有使用 Docker 编译。
- 工具链：OpenExplorer 3.7.0；hbdk4 4.7.5、hmct 2.6.5、horizon_tc_ui 3.5.3。
- 目标：nash-e，640×640，NV12 输入，INT8 PTQ（工具链对部分算子使用 INT16），O0，4 个编译线程。O2 优化未完成，部署文件是已通过实测的 O0 版本。
- 校准：20 张无人 Astra 现场画面及 bus、zidane 两张测试图片，共 22 张；按运行时规则进行等比例缩放及 127 灰色填充。
- 原模型有 365 类，person ID=0；保留原分割网络，应用与接口只输出 person。
- 量化映射报告：328 个 BPU 算子条目，0 个 CPU 算子条目。图像预处理、框筛选和分割掩膜后处理在 CPU 执行。

## 板端实测

- S100 原生 `hbm_runtime.HB_HBMRuntime`，UCP/DNN 3.13.6，指定 BPU core 0；执行实际前向推理并验证 10 个分割输出张量。
- 20 次 BPU 前向推理：中位 19.26 ms，最小 19.06 ms，最大 27.21 ms。这是网络推理耗时，不是完整应用帧率。
- 置信度阈值 0.35：bus 图片检出 4 人，zidane 图片检出 2 人，均有有效分割掩膜；无人 Astra 样本输出 0 人。
- bus 三个高置信度人物框相对浮点 ONNX 的 IoU：0.9619、0.9694、0.9627。低置信度候选有变化，不能据此声明完整数据集精度或 mAP 验收通过。
- 人物监控：BPU 后端，实时 Astra 图像 640×480，采样约 7.52 FPS，完整监控推理约 0.125 s；无加载错误，motion_enabled=false。
- 检测 API：实际测试图片及实时相机帧通过；enabled_classes=[person]，其他类别如 chair 返回 HTTP 422。
- 实时搜索：person 查询运行 4 秒处理 16 帧，无错误；验收后停止该临时搜索。
- 8 项 luka_ws 静态服务处于 active；底盘、导航和自动定位启动服务保持 inactive。没有执行移动验收。

目前现场无人，正例来自校准中使用过的测试图片；这属于功能及量化回归检查，不是独立精度评估，实人现场表现仍需补验。

## 使用与复现

当前人物监控及视觉检测接口已经使用 HBM。必要时重启：

```bash
sudo systemctl restart luka-ws-object-api luka-ws-vision luka-ws-yoloe26-live luka-ws-people
```

人物监控状态：`http://192.168.3.150:8097/api/people/status`；仪表盘：`http://192.168.3.150:8503`。

WSL uv 环境：`/home/terry/codex-bpu-yolo26-20261004/.venv`；uv 可执行文件：`/home/terry/codex-bpu-yolo26-20261004/uv-bootstrap/bin/uv`。

本机构建资料：`D:\CodexBpu\yolo26-person-20261004`。`setup_uv.sh` 安装环境，`compile_wsl.sh` 可执行完整校准和 O0 编译；`compile_o0_wsl.sh` 复用已有量化 BC，仅重新编译 HBM。依赖版本保存在 `requirements.uv.freeze.txt`，构建配置、日志和 HBM 保存在 `output`。

服务切换前的 CPU 实现备份：`/home/sunrise/luka_migration_backups/yolo26_bpu_20261004`。旧工作区 `/home/sunrise/luka_s100` 未修改。

验收数据在 HBM 同目录：`bpu_acceptance.json`、`bpu_services_acceptance.json`、`bpu_live_search_acceptance.json`；可视化：`bpu_bus_person_seg.png`。

## 官方参考

[D-Robotics YOLO26 S100 示例](https://github.com/D-Robotics/rdk_model_zoo_s/tree/s100/samples/Vision/ultralytics_yolo26)；[工具链本机安装说明](https://toolchain.d-robotics.cc/guide/env_install.html)。导出参考官方分割脚本，并显式设置 `end2end=True`，保留该权重的 one-to-one 分割头。运行代码对示例的工具模块采用独立名称，避免与既有姿态模型的 utils 模块冲突。