# YOLO26 人体链路延迟排查与修复

S100，2026-10-04；修改仅在 `/home/sunrise/luka_ws`。CPU 人脸持续关闭，HBM 模型未改动，帧龄限制仍为 0.5 秒。本次未开启移动跟随。

## 原因

1. `yolo26_bpu_person.py` 原来在 `model.predict()` 完成后才筛 person。通用后处理已先为椅子等所有检测结果完成 CPU 掩膜矩阵乘法、sigmoid、插值和裁剪，无人画面也消耗大量计算。
2. `decode_seg_layer` 把 float32 框/分数和 int64 类别编号一起 `np.stack`，预测数组因此变为 float64，掩膜系数也被提升，后续矩阵乘法做了不必要的双精度计算。
3. 小矩阵多线程 BLAS 的开销较大。实测限制为单线程后更快；人体识别服务现持久设置 `OPENBLAS_NUM_THREADS=1`、`OMP_NUM_THREADS=1`。

最初测试图的前向运行约 21 ms，后处理约 188 ms，其中掩膜处理约 184 ms。因此先前 0.3 s 左右的整个识别周期不能归因于 BPU 算力不足。

## 修改

- 通用配置新增可选 `class_id`，默认仍处理所有类别；人物调用明确设置 `class_id=0`，在 NMS/掩膜生成前过滤其他类别。
- 类别编号以 float32 参与预测数组拼接，最终返回类别仍转为整数，掩膜计算保持 float32。
- CPU 人脸 `NX_FACE_ENABLED=0` 保持生效；OSNet 人体外观描述保留。
- `person_detector.timings_ms` 可看到预处理、前向、后处理和总耗时。前向是 runtime 调用耗时，包含其调度与输出交付，并非单独芯片计数器。
- 未改变 HBM、输入分辨率、检测置信度、seg 平均深度算法和时效保护。

## 同输出对比验证

使用同一份原始 BPU 输出、单线程 BLAS，比较备份实现与优化实现：

| 图像 | 原掩膜数 → 优化后人物掩膜数 | 原后处理 → 优化后处理 |
|---|---:|---:|
| 现场无人画面 | 5 → 0 | 42.79 → 2.17 ms |
| bus 测试图 | 11 → 4 | 80.66 → 14.09 ms |
| zidane 测试图 | 2 → 2 | 26.05 → 10.53 ms |

两张人物测试图的 6 个人物框/分数对比通过；6 个掩膜 IoU 均为 1.0。这里证明的是这些样本上的结果一致性，不能等同于所有输入的精度验收。

## 实时验收

重启人体服务后，实际链路约 7.98 FPS；90 次无人画面采样中，帧龄加 HTTP 耗时中位数 0.144 s、最大 0.357 s，超过 0.5 s 的次数为 0。

另取 40 次实时检测阶段计时，中位数为：预处理 1.84 ms、前向 20.93 ms、后处理 2.48 ms、检测总计 27.00 ms。各阶段中位数不要求相加等于总计中位数。

当前约 8 FPS 是 worker 的 `CYCLE_S=.125` 软件循环上限，不代表 BPU 只能跑 8 FPS。此次实时验收镜头中无人，真人、多人和移动时的时效仍需现场验证。

人物筛选 5 项测试和分割测距 7 项测试均通过。定位到相机 TF 已接通；当前未选目标、官方跟随停用。重启后需要在页面重新点选人物。

## 文件与证据

- 代码：`perception/person_follow/bpu_yolo26_runtime/yolo26_seg.py`、`yolo26_bpu_person.py`、`worker.py`。
- 服务配置：`system/services/luka-ws-people-cpu-runtime.conf`，已安装至 systemd drop-in。
- 原文件备份：`/home/sunrise/luka_migration_backups/bpu_postprocess_20261004`。
- `evaluator/person_postprocess_validation_20261004.json`：同输出精度/性能比较。
- `evaluator/person_pipeline_optimized_20261004.json`：90 次实际链路采样。
- `evaluator/person_detector_phase_optimized_20261004.json`：40 次分阶段计时。
- `evaluator/validate_person_postprocess_20261004.py`：可复现的原实现与优化实现比较。
