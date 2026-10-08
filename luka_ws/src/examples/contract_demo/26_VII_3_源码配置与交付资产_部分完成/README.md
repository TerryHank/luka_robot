# 26 VII-3 源码配置与交付资产

合同原文：交付完整源代码、固件、配置文件、全套技术文档及接口规范文档

对照：**部分对应**。

有源码/配置/部分文档，缺STM32固件和完整接口规范；资产盘点不等于合同完整交付验收。

## 入口

    ./demo.sh           # 一键启动对应现有功能
    ./demo.sh --check   # 只核对入口，不启动服务
    ./demo.sh --plan    # 查看启动依赖
    ./demo.sh --status  # 查看状态
    ./stop.sh          # 释放本演示的服务引用

## 演示内容

终端盘点真实源码包、配置和资料目录，明确缺少的固件和接口文档。

## 代码证据

- /home/sunrise/luka_ws/src/system/environment.bash
- /home/sunrise/luka_ws/src/examples/contract_feature_traceability.md

## 验证级别

入口结构和离线/模拟检查不等于实车功能验收。没有发送实车运动目标。运行日志/状态保存在 ~/luka_data/recordings/contract_demo/。
