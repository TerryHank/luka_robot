# 03 IMU三轴实时数据演示

    ./demo.sh

入口为ROS2 launch，启动或复用现有WIT IMU节点，并在命令行持续显示
ax/ay/az（m/s^2）和gx/gy/gz（rad/s），来自实时/imu/data。
缺少新鲜数据时显示WAITING，不填造三轴值。

可选运行现有EKF，保留publish_tf=false，避免双TF发布者：

    ./demo.sh with_ekf:=true

多传感器融合还需要有效/wheel/odom。可先启动01+02，再启动03复用IMU。
只有数据观察、不启动IMU硬件：

    ./demo.sh start_hardware:=false

Ctrl+C退出，或另一终端执行./stop.sh。
代码存在不等于精度/标定/合同现场验收通过。
