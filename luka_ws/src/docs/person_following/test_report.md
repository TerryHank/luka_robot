# 构建与测试记录

## 最终结果

**PASS_STATIC / PASS_SIM；PENDING_PERSON_AND_GROUND_VALIDATION**。
用户选择本轮无人，先完成模拟和静态验收，因此不执行真人/实车运动测试。

| 测试文件 | 通过数量 | 内容 |
|---|---:|---|
| test_core_ros.py | 22 | map 几何/四元数、距离带/迟滞/限频、原 ID 恢复、新 ID 运动门槛、LOST 超时；过期感知/TF/地图、NaN、未知/占用/畸形栅格；Action 不可用/拒绝/成功/中止/取消、迟到接受和关闭节点、外部客户端不被取消、无 Twist |
| test_mot_ros.py | 1 | 两目标 ID 连续、属性/ROI/header 保留、100 个空帧后消失事件 |
| test_fusion_ros.py | 1 | 官方二进制融合真实合成掩码与16UC1深度，2m/3m厘米单位、左右方向与尺寸 |
| test_adapters_ros.py | 1 | RGB/NV12像素、尺寸/header，深度配对原数据与时间差；拒绝超限时间差、框替代掩码、NaN、错Frame、长度错误、过期数据 |
| 合计 | **25** | 0失败，0错误，0跳过 |

首轮四组 CTest 全部通过，共23项 pytest。随后增加并复现 LOST 无 Action 到达回调时永不超时的失败，修复后重跑核心22项。
其余三个未改算法的测试结果保留：总计25项 pytest。最终 colcon 汇总26项（含当前CTest汇总项），不能重复计数为26项功能测试。
原始 xunit 见 `evidence/`；远端原始文件位于 build/s100_person_following_integration/test_results/。

## 已执行构建/检查

```bash
source /opt/ros/humble/setup.bash
source /home/sunrise/luka_ws/install/local_setup.bash
cd /home/sunrise/luka_ws
colcon build --base-paths src --packages-select tros_person_following s100_person_following_integration --symlink-install --executor sequential
colcon build --base-paths src --packages-select hobot_mot s100_person_following_integration --symlink-install --executor sequential
# 最后一次核心修复
colcon build --base-paths src --packages-select tros_person_following --symlink-install --executor sequential
source src/system/scripts/person_follow_environment.bash
colcon test --base-paths src --packages-select s100_person_following_integration --executor sequential
colcon test --base-paths src --packages-select s100_person_following_integration --executor sequential --ctest-args -R core_ros
colcon test-result --test-result-base build/s100_person_following_integration --verbose
python3 src/system/scripts/check_workspace_root.py
```

受影响三个包均已在 S100 构建。未重建原 SLAM、Nav2、Costmap 或底盘。
上游完整 Git clone/fsck、VIMS整包校验、依赖 ldd、Python AST、bash -n、唯一包发现和根目录规范通过。
源文件保留原 CRLF 风格；使用单条 git diff 命令的 cr-at-eol 规则检查空白，无修改全局 Git 配置。
环境脚本用 ROS_DOMAIN_ID=99、RMW_IMPLEMENTATION=rmw_fastrtps_cpp 测试后保持原值，不强制覆盖生产中间件配置。

## 实采但不是人体跟随验收

最后一次25.01秒采样：color661帧、depth662帧、分割229帧、融合229帧、MOT228帧。
按含启动过程的窗口计算约26.4/26.5/9.2/9.2/9.1Hz。
掩码为160×120，原图和深度640×480；配对最大绝对原时间差约12.59ms，小于40ms限值。
观测接收延迟均值：分割0.266s、融合0.280s、MOT0.281s；最大约0.65s，含观测器阻塞/启动和后台编辑器负载。
这不是 camera→Goal 延迟，也不代表已满足实车0.6秒新鲜度门槛；该门槛仍保留。
一次资源快照：camera约45.7%单核CPU/102MiB，格式适配约104%/136MiB，DNN约22%/82.8MiB，配对约19.1%/81.5MiB，融合约10.5%/82.4MiB，核心约1.8%/23.7MiB；BPU单次ratio为1，不代表峰值。
当时另有VS Code索引进程与构建/测试负载，不能作为产品最终性能结论。
现场无人，融合/MOT输出为空目标数组。所有本轮感知进程已正常退出，既有服务未重启。

## 遗留验收

T1 的实际 Nav2/Costmap 和 map/base/camera TF 未就绪；T2/T3 的真实人体ROI与测距、T4真人多人遮挡、T10实车跟随尚未执行。
本轮没有真实导航目标、真实Action取消、底盘速度指令或物理跟随动作。
MOT身份不等于ReID永久身份。直接转向扫描禁用，SIGKILL/超过3秒才返回的Goal响应不在优雅关闭保证范围。
