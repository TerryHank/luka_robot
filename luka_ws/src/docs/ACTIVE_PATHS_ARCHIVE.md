# Luka 当前功能通路与归档结果

日期：2026-10-08。工作区：`/home/sunrise/luka_ws`。
本次仅整理源码、依赖与启动引用；未发送实车导航目标或速度命令。

## 当前保留的实现

| 旧目录/内容 | 当前保留位置 | 处理结果 |
| --- | --- | --- |
| `src/perception/person_follow` 的私人跟随/人体追踪实现 | `src/control/tros_person_following`、`src/control/s100_person_following_integration` | 旧实现退出工作区；当前只使用官方 MOT 与跟随通路 |
| 旧 person_follow 中的人脸身份功能 | `src/perception/luka_face_identity` | 独立 ROS/HTTP 包；消费官方 MOT ID 与 ROS 图像，不创建另一套人体追踪或运动授权 |
| `src/perception/object_api` | `src/perception/luka_image_inference` | 保留图片 HTTP 推理接口；当前 BPU 模型仅支持 person，不是通用开放词表模型 |
| `src/perception/locateanything_trial_20260907` | `src/perception/luka_visual_runtime` | 保留预览、录像检索、对象/语义记忆；使用 Orbbec ROS RGB-D |
| `src/perception/yoloe26_live` | `src/perception/luka_live_detection` | 保留当前 live HTTP 接口；移走未使用的 venv、ONNX 与 wheel |
| `src/perception/spatial_memory` | 视觉包内 `orbbec_ros_camera.py` 与 `rgbd_geometry.py` | 保留实际需要的 ROS 图像消费和深度几何；旧相机应用和 NX 后端退出工作区 |
| `src/control/luka_person_following` | `src/system/scripts/start_official_person_following.sh` | 旧 ROS 兼容包退出源码和安装索引；脚本别名委托官方入口 |
| 音频 vendor 中的旧 ROS 包装 | `src/common/vendor/sensevoice_sdk`、`src/common/vendor/wetts_sdk` | 仅保留当前 ASR/TTS 需要的 SDK；音频包构建与 bootstrap 路径已适配 |
| `src/system/nx_chat` 的源码/构建参考 | `install/luka_llm_runtime` | 当前编译运行时保留，服务路径已迁移；模型选择另见下文 |
| `src/common/legacy` 中实际使用的数据 | `src/common/config`、`src/common/state`、`log` | 保留用到的音频配置、旧路线数据和导航日志，其他旧资料退出源码 |
| 旧 ROS1 map_merge、忽略的 vision_opencv 源码及 dated evaluator worker/bundles | 工作区外历史材料 | 不参与当前包发现、构建或启动 |

仍使用的音频虚拟环境和私有 AIUI SDK 是必要运行依赖，未按旧缓存删除。
接口包、服务层和安全层因职责不同而保留；不是仅凭名字相似删除。

## 数据与启动

- 身份库仍为 `~/luka_data/recordings/person_follow/people.sqlite3`。
- YuNet/SFace 仍为 `~/luka_data/ml_models/person_follow/` 下原文件。
- 录像仍保留在 `~/luka_data/recordings/locateanything_trial_20260907/`；目录名称保留历史关联，不代表保留旧代码实现。
- 源码均在 `luka_ws/src/<domain>`，工作区根目录没有兼容快捷方式。
- `functional_owners.json` 已更新；唯一性检查禁止恢复已淘汰实现。
- 物理相机使用 `astra-camera.lock`，只读视觉消费者使用独立 `visual-runtime.lock`，不会阻止唯一的 USB 相机所有者。

一键入口均在 `src/system/scripts/`：

```bash
# 默认沿用官方 dry_run；不在无人验收中授权运动
./src/system/scripts/start_official_person_following.sh

# 人脸服务默认不启用推理，由现有 HTTP start 操作显式启用
./src/system/scripts/start_face_identity.sh
./src/system/scripts/start_image_inference.sh
./src/system/scripts/start_orbbec_vision.sh
```

人脸服务保留 loopback 8098 与兼容 8097；图片推理保留 8096；视觉页面保留 8091。
人脸身份匹配不是运动授权；旧 confirm-target 运动授权入口明确拒绝。
现有 people/object-api/vision systemd 路径已适配，但本次未启动生产感知或运动服务。

## 已验证与边界

| 验证项 | 结果 |
| --- | --- |
| `colcon list --base-paths src` 与物理包名扫描 | 23 个包，包名唯一；11 个功能所有者检查通过 |
| 根目录结构检查 | 通过；源码域全部在 src 下 |
| 完整工作区构建 | 23 个包全部通过；修复两处旧生成目录与 symlink 构建冲突 |
| 拆包后的定向 pytest | 38 项通过：人脸身份/实际 ROS 合成消息、图片 HTTP、RGB-D 几何/同步、唯一入口检查 |
| 此前相关回归 | 41 项通过；与上述结果有重合，不能相加计算覆盖数 |
| 官方跟随集成包 colcon test | 29 tests，0 errors/0 failures/0 skipped；含测试汇总层级，不是额外 29 项独立功能 |
| 实际 BPU 空白图推理 | 通过，0 个 person 检出；不证明真人识别效果 |
| 视觉服务启动/HTTP 页面读回 | 通过；隔离 ROS domain 等待注册 RGB-D，未打开 USB 相机、未发送运动 |
| 当前 LLM 运行库路径 | ldd 无缺失库，不依赖退休源码目录；模型是否部署可用单独核查 |

修复了视觉应用和录像模块缺失的 Path 导入。
人脸身份输出在图像或 MOT 任一输入过期时清空。
退休路径扫描只发现功能注册表的禁止恢复清单，没有当前执行入口引用旧目录。
旧 `luka_person_following` 已不能通过 `ros2 pkg prefix` 找到；新包索引可正常解析。

未进行真人识别、落地跟随或导航验收。未重新运行全量工作区测试；此前旧 voice/object 测试预期失败不包含在本次定向通过结果中。
官方隔离依赖前缀仍有缺少 local_setup 文件的 colcon 警告，相关包的完整构建和指定回归已通过。

## 用户清理后的回退状态

原归档为 `~/luka_archives/active-paths-20261008`，原始迁移清单、修改前 diff、旧源码、旧环境和服务备份在本轮校验时已不存在。
用户确认因磁盘空间不足主动清理了归档；本次没有重新复制这份大归档。

当前该目录约 60 KB 的剩余材料已校验；`ARCHIVE_SHA256.json` **只覆盖这些剩余文件**，不代表已删除的旧归档仍可校验。
原归档缺失后，不能再证明完整的迁移前未提交状态可恢复。
Git HEAD `ee590e15d4fc4d434ccec5c0bedfb9b6cd17a5f6` 和 Git 历史仍在，已提交源码可以恢复。
另有 `~/luka_architecture_final_20261007` 的较早快照，它不是本次迁移前精确状态。

当前身份数据库和模型未丢失。
原 Qwen 4B GGUF 仍在 `~/luka_s100/nx_chat/models/`，当前 chat 服务引用的 `~/luka_data/ml_models/nx_chat/` 目录为空。
另存在 `~/luka_data/ml_models/oellm/Qwen2.5_7B_Instruct_1024.hbm`；它不是 llama-server 可直接读取的 GGUF。
用户已确认正在切换 OELLM，暂不恢复 Qwen 4B。本轮不移动新模型、不启用旧 chat 服务；OELLM 切换本身不包含在本轮通路验收结果中。

## 证据

- `log/active_path_final_verification.log`：完整构建记录。
- `log/active_path_final.xunit.xml`：38 项定向测试最终结果。
- `log/active_runtime_smoke.stdout`、`log/active_visual_runtime_smoke.json`：启动与模型检查。
- `log/active_package_names.txt`：当前发现的 23 个包。
- `log/active_retired_reference_scan.json`：退休路径扫描。
- `log/active_archive_verification.json`：剩余小归档校验结果。

未重置 Git，未提交或推送本轮修改；已有用户修改保留。

