#!/usr/bin/env bash
set -eo pipefail
# Stop only the canonical services owned by systemd; never kill unrelated ROS clients.
sudo -n systemctl stop luka-ws-hardware@navigation.service luka-ws-hardware@localization.service
echo '导航/定位服务已请求停止；独立终端启动的实例请在所属终端 Ctrl+C。'
