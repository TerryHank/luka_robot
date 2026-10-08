# 23 VI-4 应用接口规范资料

合同原文：统一输出完整《应用接口规范文档》，包含通信协议、数据帧格式、指令定义、异常处理、对接调试说明。

对照：**部分对应**。

有API路由、ROS消息和追溯资料；没有确认的完整合同应用接口规范。本入口查看已有接口结构，不能替代正式交付文档。

## 入口

    ./demo.sh           # 一键启动对应现有功能
    ./demo.sh --check   # 只核对入口，不启动服务
    ./demo.sh --plan    # 查看启动依赖
    ./demo.sh --status  # 查看状态
    ./stop.sh          # 释放本演示的服务引用

## 演示内容

查看已有工具接口与ROS消息定义，不把追溯表冒充完整应用接口规范。

## 代码证据

- /home/sunrise/luka_ws/src/visualization/console/nx_assistant_tools.py
- /home/sunrise/luka_ws/src/examples/contract_clause_traceability_strict.md

## 验证级别

入口结构和离线/模拟检查不等于实车功能验收。没有发送实车运动目标。运行日志/状态保存在 ~/luka_data/recordings/contract_demo/。
