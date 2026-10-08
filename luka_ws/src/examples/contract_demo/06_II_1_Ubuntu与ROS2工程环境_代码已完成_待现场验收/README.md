# 06 II-1 Ubuntu与ROS2工程环境

合同原文：Ubuntu22.04 + ROS2 完整开发环境搭建、项目工程框架搭建。

对照：**有对应实现，现场待验收**。

已核实Ubuntu22.04.5、ROS2 Humble及当前17个真实ROS源码包。

## 入口

    ./demo.sh           # 一键启动对应现有功能
    ./demo.sh --check   # 只核对入口，不启动服务
    ./demo.sh --plan    # 查看启动依赖
    ./demo.sh --status  # 查看状态
    ./stop.sh          # 释放本演示的服务引用

## 演示内容

终端显示实际OS、ROS安装包及规范目录位置；不启动设备。

## 代码证据

- /home/sunrise/luka_ws/src/system/environment.bash

## 验证级别

入口结构和离线/模拟检查不等于实车功能验收。没有发送实车运动目标。运行日志/状态保存在 ~/luka_data/recordings/contract_demo/。
