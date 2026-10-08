# 合同功能操作与验收手册

主册为01–25共25项功能；01/02共享场景，26/27为交付与服务附录。目录编号保持原样。
**本手册是验收操作计划，不是已经通过的验收报告。界面按钮不补齐缺失的固件、传感器或业务闭环。**

## 通用启动与停止

先在Windows PowerShell设置：

    $demoScript="D:\Workspace\foxglove-studio-cn\integrations\luka-contract-demo\start_demo.ps1"

然后：powershell.exe -NoProfile -ExecutionPolicy Bypass -File $demoScript -Item NN -Run。
无-Run只连接/选布局。01/02默认使用Foxglove原生方向键，终端键盘可在远端显式keyboard:=true启用。
完成一项后Ctrl+C，另一个窗口可运行对应stop.sh；不要仅关闭Foxglove当作停止。
01与09/04组合时先启动01，再启动算法；停止时先算法再01。SLAM与AMCL互斥。

## 记录规则

每项填写操作者、日期、软件版本、测试条件、目标指标、实测值、原始日志/视频、异常/恢复、结论和未覆盖项。
合同未给定的精度/时长/响应门槛由双方先填写；下面示例数值不替代约定。
只测到已实现部分时记录“部分通过”，不能把整项勾成通过。缺失项标阻塞，服务项用履约资料。

## 01 I-1 STM32与通信协议

当前：部分完成

启动：powershell.exe -NoProfile -ExecutionPolicy Bypass -File $demoScript -Item 01 -Run

操作：启动01；原生控制→启用本次方向操作→低速方向键，逐一短按前/后/左移/右移/转向，松开和立即停车。

观察与证据：记录/wheel/odom、底盘gate、通信错误日志；观察反馈是否连续且松开停止。

通过条件／阻塞：上位机链路演示可通过；整项还需STM32固件、串口/RS485/CAN协议及异常恢复实测。当前缺固件/CAN，不能整项通过。

代码限制：只有上位机RS485/Modbus协议代码；没有STM32固件工程和CAN实现。

独立停止：ssh sunrise@192.168.3.150 "python3 /home/sunrise/luka_ws/src/examples/contract_demo/_shared/stop_launch.py drive_odom"

## 02 I-2 运动学编码器与速度闭环

当前：部分完成

启动：powershell.exe -NoProfile -ExecutionPolicy Bypass -File $demoScript -Item 02 -Run

操作：复用01场景；按事先量好的直线距离（例如0.50m）低速前进、停车，再验证后退/横移/转向。

观察与证据：终端x/y/yaw、vx/vy/wz、measured_path与尺量/角度测量对照；记录设定速度、实测速度和停止误差。

通过条件／阻塞：双方填写距离/角度/速度误差容限并验证闭环；当前麦克纳姆与合同四轮差速存在车型差异，需先明确验收模型。

代码限制：实际为四轮麦克纳姆运动学，非合同字面差速；编码器/闭环现场效果待验收。

独立停止：ssh sunrise@192.168.3.150 "python3 /home/sunrise/luka_ws/src/examples/contract_demo/_shared/stop_launch.py drive_odom"

## 03 I-3 IMU与卡尔曼融合

当前：代码已完成_待现场验收

启动：powershell.exe -NoProfile -ExecutionPolicy Bypass -File $demoScript -Item 03 -Run

操作：启动03看原始六轴；改变可测试的传感器姿态和角运动。融合测试先启动01，再在第二个终端03 -WithEkf -Run。

观察与证据：加速度/角速度/姿态/协方差及时间戳；EKF面板需出现/contract_demo/odometry/filtered，同时有有效/wheel/odom。

通过条件／阻塞：必须验证六轴、姿态及多传感器融合，不把默认原始IMU显示当完整融合验收。偏置、噪声和精度门槛由双方填写。

代码限制：复用IMU驱动和二维EKF；演示滤波器不发布TF，避免与现有里程计重叠。现场标定与精度未验收。

融合启动加参数 -WithEkf；需要有效轮里程计。

独立停止：ssh sunrise@192.168.3.150 "python3 /home/sunrise/luka_ws/src/examples/contract_demo/_shared/stop_launch.py imu_axes"

## 04 I-4 雷达滤波与去畸变

当前：部分完成

启动：powershell.exe -NoProfile -ExecutionPolicy Bypass -File $demoScript -Item 04 -Run

操作：启动04；在视野内移动/遮挡一个测试目标，对照原扫描、融合和去畸变。运动去畸变测试先启动01再运行04。

观察与证据：扫描点数、最近距离、目标位置、原/去畸变差异和时间戳。静止输出相同不能证明去畸变效果。

通过条件／阻塞：驱动/滤波/稳定性及受控运动去畸变均需记录；目前是2D LaserScan，不应宣称已交付完整3D点云链。

代码限制：当前主要数据是二维LaserScan，不是完整3D点云；去畸变演示输出独立话题。

独立停止：ssh sunrise@192.168.3.150 "python3 /home/sunrise/luka_ws/src/examples/contract_demo/_shared/stop_launch.py lidar"

## 05 I-5 RGBD深度相机

当前：代码已完成_待现场验收

启动：powershell.exe -NoProfile -ExecutionPolicy Bypass -File $demoScript -Item 05 -Run

操作：启动05；图像面板观察不同距离目标，移动目标；与尺量距离对照，可在图像中查看深度像素。

观察与证据：RGB、彩色16UC1深度图、终端中心深度（米）、图像帧计数、有效像素/盲区。

通过条件／阻塞：预先填写距离误差、持续时长、帧率和允许丢帧阈值；逐距离实测而非只确认一帧图像。

代码限制：Astra Pro Plus驱动和RGB-D预处理存在；实时帧率和深度质量需要现场验证。

独立停止：ssh sunrise@192.168.3.150 "python3 /home/sunrise/luka_ws/src/examples/contract_demo/_shared/stop_launch.py camera"

## 06 II-1 Ubuntu与ROS2工程环境

当前：代码已完成_待现场验收

启动：powershell.exe -NoProfile -ExecutionPolicy Bypass -File $demoScript -Item 06 -Run

操作：执行06检查；Foxglove原始消息/Topic Graph查看状态；终端查看资源和服务。另按交付流程从干净源码完成colcon构建、测试、重新启动。

观察与证据：Ubuntu/ROS版本、唯一包名、构建/测试结果及可复现环境/依赖清单。

通过条件／阻塞：完整开发环境可复现构建和运行，所有阻断失败解决；包目录存在或入口检查不是全量构建通过。

代码限制：已核实Ubuntu22.04.5、ROS2 Humble；包数以colcon list为准（本轮发现18个唯一包，不等于全量构建验收）。

## 07 II-2 消息接口与话题封装

当前：部分完成

启动：powershell.exe -NoProfile -ExecutionPolicy Bypass -File $demoScript -Item 07 -Run

操作：启动07；比较原始消息字段、时间戳、单位和命名空间；对照已交付接口规范与订阅端。

观察与证据：标准Odometry/IMU、已有ai_msgs/语义地图接口；记录序列化和无效输入处理。

通过条件／阻塞：底盘/传感/控制专用接口需覆盖合同范围并与规范一致；当前标准消息覆盖不能证明完整专用消息封装。

代码限制：有ai_msgs和语义地图自定义消息；底盘控制仍大量使用标准Twist/Odometry，不能宣称有完整专用底盘协议消息。

独立停止：ssh sunrise@192.168.3.150 "python3 /home/sunrise/luka_ws/src/examples/contract_demo/_shared/stop_launch.py interfaces"

## 08 II-3 分层ROS节点

当前：部分完成

启动：powershell.exe -NoProfile -ExecutionPolicy Bypass -File $demoScript -Item 08 -Run

操作：启动08；查看实际节点、数据流、相机、位姿、地图和路径，逐层核对上游/下游。

观察与证据：节点图、唯一设备/TF/速度出口所有者、异常/恢复日志。

通过条件／阻塞：底盘→感知→定位→规划→安全执行链贯通；缺失的回充节点不能用占位节点代替。

代码限制：有底盘/雷达/IMU/SLAM/Nav2；自动回充业务闭环缺失。

独立停止：ssh sunrise@192.168.3.150 "python3 /home/sunrise/luka_ws/src/examples/contract_demo/_shared/stop_launch.py layers"

## 09 III-1 二维激光SLAM

当前：代码已完成_待现场验收

启动：powershell.exe -NoProfile -ExecutionPolicy Bypass -File $demoScript -Item 09 -Run

操作：先启动01，用Foxglove方向键；另一个终端启动09，复用已有底盘/传感器，低速经过预定闭合路线。

观察与证据：地图连续增长、墙体形状和闭环前后；位姿/扫描与地图对齐；记录漂移、覆盖、误差。

通过条件／阻塞：按预定地图质量/误差容限通过真实建图和闭环；先停止09再停止01。不要同时启动AMCL/static map。

代码限制：只启动现有slam_toolbox算法节点，复用当前传感器和只读里程计；不调用旧ESP32通用整机launch。现场调优未验收。

独立停止：ssh sunrise@192.168.3.150 "python3 /home/sunrise/luka_ws/src/examples/contract_demo/_shared/stop_launch.py slam"

## 10 III-2 地图保存加载与复用

当前：部分完成

启动：powershell.exe -NoProfile -ExecutionPolicy Bypass -File $demoScript -Item 10 -Run

操作：保持09 SLAM活跃；在09原生控制点击保存当前SLAM地图，服务自动生成新文件名。停止SLAM，再用10 -MapYaml <保存结果中的YAML绝对路径>离线加载。3D显示地图不等于Nav2地图已切换；重启复用需另核开机参数。

观察与证据：map图像/YAML/posegraph文件与保存日志，重新加载后的尺寸/分辨率/关键结构和启动路径。

通过条件／阻塞：保存、离线加载及断电重启自动复用全部实测；本次只加保存按钮，不自动改开机配置或覆盖生产地图。

代码限制：提供静态地图加载入口和独立save_map.sh；保存调用已有mapping_bundle且要求SLAM活跃。断电自动复用未实测。

独立停止：ssh sunrise@192.168.3.150 "python3 /home/sunrise/luka_ws/src/examples/contract_demo/_shared/stop_launch.py map"

## 11 III-3 全局重定位与场景匹配

当前：部分完成

启动：powershell.exe -NoProfile -ExecutionPolicy Bypass -File $demoScript -Item 11 -Run

操作：停止SLAM并启动11；在3D使用发布位姿估计工具向/initialpose发初始位姿，核对扫描与地图重合；原网页自动定位入口已停用。

观察与证据：amcl_pose/协方差、map→odom→base_link和定位页面的核验结果；记录多位置/多朝向恢复。

通过条件／阻塞：达到约定重定位误差与时间，并覆盖场景变化；自动定位可能执行原地旋转，必须由操作者明确开始。

代码限制：有AMCL/全局重定位/扫描匹配；本入口不自动调用可能旋转底盘的重定位请求。场景适应效果未验收。

独立停止：ssh sunrise@192.168.3.150 "python3 /home/sunrise/luka_ws/src/examples/contract_demo/_shared/stop_launch.py localization"

## 12 IV-1 全局局部路径规划

当前：代码已完成_待现场验收

启动：powershell.exe -NoProfile -ExecutionPolicy Bypass -File $demoScript -Item 12 -Run

操作：启动12并完成定位核验；3D发布位姿到/contract_demo/goal_pose暂存目标，再点击原生控制的执行暂存导航目标，途中停止，再换目标。

观察与证据：/contract_demo/navigation_status、/plan、实测里程计、到达结果、停止确认；检查控制门拒绝原因。

通过条件／阻塞：按预定目标容差/规划条件/失败处理通过多组路线；启动成功和画出路径不代表实车到达。

代码限制：启动现有Nav2规划/控制后端；不会自动发目标，现场调优和运动效果未验收。

独立停止：ssh sunrise@192.168.3.150 "python3 /home/sunrise/luka_ws/src/examples/contract_demo/_shared/stop_launch.py navigation"

## 13 IV-2 静态与动态避障

当前：部分完成

启动：powershell.exe -NoProfile -ExecutionPolicy Bypass -File $demoScript -Item 13 -Run

操作：启动13并核验定位；由操作者给目标。分别做静态绕行、动态目标进入/离开、阻塞与清除测试。

观察与证据：融合扫描、代价地图、碰撞监视状态、安全速度、距离与停车/恢复过程视频。

通过条件／阻塞：填写最小安全距离、停止距离/响应时间和恢复策略；不得仅用激光点出现证明动态避障闭环。

代码限制：代价地图/CollisionMonitor存在；动态行人实时避障完整闭环仍需现场验收。

独立停止：ssh sunrise@192.168.3.150 "python3 /home/sunrise/luka_ws/src/examples/contract_demo/_shared/stop_launch.py avoidance"

## 14 IV-3 航点巡航与软件返航

当前：部分完成

启动：powershell.exe -NoProfile -ExecutionPolicy Bypass -File $demoScript -Item 14 -Run

操作：启动14；3D发布位姿话题改为/patrol/add_pose添加多个点；原生控制保存/读回路线、巡航一圈、暂停/恢复和停止；停留时间需在路线YAML中设置，界面没有编辑器。

观察与证据：界面当前实际任务状态、路线与每站到达/停留结果；补测点位记忆和软件返航。

通过条件／阻塞：多点执行、路线保存再读、取消/失败处理、返航均需现场验证；界面运行状态优先，不用闲置后台节点状态推断成功。

代码限制：航点/巡航/Home节点存在；无充电停靠闭环，入口只启动节点且不自动发航点/返航/巡航请求。

独立停止：ssh sunrise@192.168.3.150 "python3 /home/sunrise/luka_ws/src/examples/contract_demo/_shared/stop_launch.py business"

## 15 IV-4 缓启停与运动平滑

当前：代码已完成_待现场验收

启动：powershell.exe -NoProfile -ExecutionPolicy Bypass -File $demoScript -Item 15 -Run

操作：启动15；定位后通过3D暂存目标和原生执行按钮发导航目标，包含起步、转弯、减速和停止；方向键不是Nav2平滑链测试。

观察与证据：raw/smoothed/guarded/safe速度曲线与实测轮速；记录加速度、转弯速度及停止过程。

通过条件／阻塞：填写平滑/限速指标，用实际运动对照；不直接给/nav_safe注入测试速度。

代码限制：复用Nav2 velocity_smoother和限幅函数；不直接注入速度，物理平稳性仍需运动验收。

独立停止：ssh sunrise@192.168.3.150 "python3 /home/sunrise/luka_ws/src/examples/contract_demo/_shared/stop_launch.py smoothing"

## 16 V-1 充电桩标定与识别

当前：未实现

启动：powershell.exe -NoProfile -ExecutionPolicy Bypass -File $demoScript -Item 16 -Run

操作：当前未实现。准备充电桩、识别信号接口和标定数据，补齐源码/运行链后再开始测试。

观察与证据：桩检测原始数据、桩坐标、误识别/丢失状态和标定误差。

通过条件／阻塞：缺充电桩识别/标定完整实现，当前阻塞。软件Home点不能替代充电桩。

代码限制：有若干docking_server参数样例，但没有确认的桩识别/标定完整实现和在用启动链。配置段不作为实现证据。

## 17 V-2 精准停靠与充电

当前：部分完成

启动：powershell.exe -NoProfile -ExecutionPolicy Bypass -File $demoScript -Item 17 -Run

操作：启动17并核验定位；原生控制按钮设置当前点为软件Home，离开后点击软件返航；核对/home/status并测试取消。

观察与证据：Home配置/pose、返航执行状态、实测最终位置和取消停稳。

通过条件／阻塞：目前只支持软件Home；精准对位、自动停靠和充电检测未形成闭环，因此整项充电验收仍阻塞。

代码限制：仅能演示软件Home节点与返航接口；精准对位、停靠和充电未形成闭环。

独立停止：ssh sunrise@192.168.3.150 "python3 /home/sunrise/luka_ws/src/examples/contract_demo/_shared/stop_launch.py home"

## 18 V-3 低电量自动回充

当前：未实现

启动：powershell.exe -NoProfile -ExecutionPolicy Bypass -File $demoScript -Item 18 -Run

操作：当前未实现。补齐电量接口、阈值触发、重试及回充路径后，使用受控电量输入做各边界场景。

观察与证据：真实/受控电量来源、阈值、触发任务、失败重试、遇障回充和停止结果。

通过条件／阻塞：当前缺低电量自动回充实现，阻塞；不能用人工点击Home冒充低电量触发。

代码限制：未找到可运行的低电量触发、回充重试及绕障回充闭环。

## 19 V-4 充电检测脱离与待机

当前：未实现

启动：powershell.exe -NoProfile -ExecutionPolicy Bypass -File $demoScript -Item 19 -Run

操作：当前未实现。补齐充电电流/状态、充满判定、基站脱离与待机链后按设备条件测试。

观察与证据：充电状态、充满判据、脱离过程及待机功耗/状态记录。

通过条件／阻塞：当前缺充电检测及自主脱离闭环，阻塞；未充电的静止状态不是充满待机。

代码限制：未找到充电状态检测及充满自主脱离闭环。

## 20 VI-1 声源方位与语音导航

当前：部分完成

启动：powershell.exe -NoProfile -ExecutionPolicy Bypass -File $demoScript -Item 20 -Run

操作：启动20；原生控制→播报文字；实际唤醒用麦克风，分别从预定方向发声，查看识别文本和新鲜DOA；趋近动作仅由操作者明确执行。

观察与证据：语音文本、DOA来源时间/角度/校准、Agent反馈、任务执行及取消结果。

通过条件／阻塞：接口规范、实时声源检测、转向/趋近和整机适配全覆盖；历史DOA或文字命令不能证明声源导航。

代码限制：DOA/语音路由/Agent有代码；当前DOA记录不能代替新鲜实时检测；声源趋近完整联动未验收。需要有效NX_MIC/NX_SPEAKER配置。

独立停止：ssh sunrise@192.168.3.150 "python3 /home/sunrise/luka_ws/src/examples/contract_demo/_shared/stop_launch.py voice"

## 21 VI-2 烟雾告警与联动

当前：未实现

启动：powershell.exe -NoProfile -ExecutionPolicy Bypass -File $demoScript -Item 21 -Run

操作：当前未实现。补齐传感器/阈值/业务接口后，按设备认可的测试方法做正常、报警、断联和恢复。

观察与证据：烟雾原始读数、阈值、告警事件及返航/值守任务关联记录。

通过条件／阻塞：当前缺烟雾采集和联动实现，阻塞；不要用手工消息替代真实传感器验收。

代码限制：未找到烟雾传感器驱动、阈值报警和返航/值守联动实现。

## 22 VI-3 人脸识别与身份接口

当前：部分完成

启动：powershell.exe -NoProfile -ExecutionPolicy Bypass -File $demoScript -Item 22 -Run

操作：启动22；查看face_image，首个合格脸是本次内存参考；同一/不同人再次出现，记录接受/拒绝和相似度。

观察与证据：参考相似度、误识别、遮挡/离场再出现结果；身份库/权限/迎宾需另查实际接口。

通过条件／阻塞：当前参考比对只是部分功能；身份认证、权限联动、持久脸库和迎宾导航缺少完整证据，不可整项通过。

代码限制：生产人员服务NX_FACE_ENABLED=0。独立只读演示复用YuNet/SFace，显示参考帧相似度，不修改生产开关，不声称权限联动或迎宾导航已实现。

独立停止：ssh sunrise@192.168.3.150 "python3 /home/sunrise/luka_ws/src/examples/contract_demo/_shared/stop_launch.py face"

## 23 VI-4 应用接口规范资料

当前：部分完成

启动：powershell.exe -NoProfile -ExecutionPolicy Bypass -File $demoScript -Item 23 -Run

操作：执行23资料检查；阅读完整应用接口规范，选一条控制、传感、异常接口按规范与实际实现逐字段对照。

观察与证据：通信协议、帧格式、单位、指令、错误码、超时及对接例程，注明版本/修订。

通过条件／阻塞：源码/API列表不能替代正式完整接口规范；当前资料缺口需补齐。

代码限制：有API路由、ROS消息和追溯资料；没有确认的完整合同应用接口规范。本入口查看已有接口结构，不能替代正式交付文档。

## 24 VII-1 整机业务状态机

当前：部分完成

启动：powershell.exe -NoProfile -ExecutionPolicy Bypass -File $demoScript -Item 24 -Run

操作：启动24；明确下发一个任务，在原生控制测试暂停、恢复、取消，再做人工接管和传感器故障状态切换。

观察与证据：mission/status、安全/goal状态、实际停稳与恢复行为；重启前后任务状态记录。

通过条件／阻塞：待机、手动、建图、导航、巡航、回充、故障和联动逐态覆盖；回充及部分联动缺项仍阻止整项通过。

代码限制：已有任务暂停/恢复/取消及状态接口；回充相关状态和完整传感器业务联动缺少证据。

独立停止：ssh sunrise@192.168.3.150 "python3 /home/sunrise/luka_ws/src/examples/contract_demo/_shared/stop_launch.py state_machine"

## 25 VII-2 故障自检与运行日志

当前：代码已完成_待现场验收

启动：powershell.exe -NoProfile -ExecutionPolicy Bypass -File $demoScript -Item 25 -Run

操作：启动25；Foxglove原始消息核对设备状态，终端保存诊断日志。无运动任务时对一个可恢复传感器做断联/恢复，记录全过程。

观察与证据：实际健康状态变化、故障原因、时间戳、日志/快照和恢复结果；保存原始日志。

通过条件／阻塞：约定检测/上报时限，验证真实异常及恢复；软件健康页全绿不表示未安装传感器也已验收。

代码限制：软件健康检查、故障快照与日志链存在；传感器断联会如实显示未就绪。

独立停止：ssh sunrise@192.168.3.150 "python3 /home/sunrise/luka_ws/src/examples/contract_demo/_shared/stop_launch.py diagnostics"

## 26 VII-3 源码配置与交付资产

当前：部分完成

启动：powershell.exe -NoProfile -ExecutionPolicy Bypass -File $demoScript -Item 26 -Run

操作：核对源码、固件、配置、模型/地图必要资产、构建方法及技术文档交付清单。

观察与证据：版本号/提交、文件清单/校验、依赖许可、可恢复与复现记录。

通过条件／阻塞：当前缺STM32固件和完整接口规范；源码目录或备份不是完整交付验收。

代码限制：有源码/配置/部分文档，缺STM32固件和完整接口规范；资产盘点不等于合同完整交付验收。

## 27 VII-4 培训质保与维护

当前：服务承诺_待核实

启动：powershell.exe -NoProfile -ExecutionPolicy Bypass -File $demoScript -Item 27 -Run

操作：核对培训记录、使用材料、质保起止和维护受理/交付记录。

观察与证据：培训签到/录像/材料、质保和维护履约资料。

通过条件／阻塞：这是服务履约，不能通过ROS launch或Foxglove按钮证明完成。

代码限制：培训、一年质保和维护属于服务承诺，不能通过launch/sh或源码证明履约。
