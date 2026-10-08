#!/usr/bin/env bash
set -Eeuo pipefail
ws=/home/sunrise/luka_ws
# No autonomous navigation, exploration, elevator control or localization spin.
env TUNING_ENV_FILE=/dev/null MODE=slam RESTART_FOXGLOVE=0 \
    MAX_LINEAR_SPEED=0.15 MAX_ANGULAR_SPEED=0.35 MAX_MOTOR_RPM=60 \
    AUTO_LOCALIZER_ENABLE_ROTATION=false AUTO_LOCALIZER_ENABLE_ESCAPE=false \
    ENABLE_PATROL_MANAGER=false ENABLE_NAMED_NAVIGATION=false ENABLE_MISSION_CONTROL=false \
    ENABLE_HOME_MANAGER=false ENABLE_FINAL_APPROACH=false ENABLE_MULTIFLOOR_MANAGER=false \
    ENABLE_ELEVATOR_ADAPTER=false ENABLE_ELEVATOR_ENTRY_CONTROLLER=false \
    ENABLE_WATERPLUS_BRIDGE=false ENABLE_DEPTH_CAMERA=false ENABLE_SEMANTIC_MAPPING=false \
    SLAM_MAP_UPDATE_INTERVAL=1.0 \
    bash "$ws/restart_nav_reset.sh"
systemctl --user stop person-follow.service
bash "$ws/tools/start_lightweight_dashboard.sh" start
echo '手动建图启动流程已完成。请先在页面检查 SLAM 状态及实时地图，再用手柄慢速带车。'
