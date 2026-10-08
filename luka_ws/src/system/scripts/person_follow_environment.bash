#!/usr/bin/env bash
# Only extends this shell; does not change ROS_DOMAIN_ID or RMW_IMPLEMENTATION.
source /opt/ros/humble/setup.bash
source /home/sunrise/luka_ws/install/local_setup.bash
_follow_fusion=/home/sunrise/luka_upstream/vims-fusion-0.0.6/install
_follow_dnn=/home/sunrise/luka_upstream/s100-dnn/extracted/opt/tros/humble
if [[ ! -f "$_follow_fusion/lib/libhobot_obstacle_depth_fusion_plugin.so" ||
      ! -x "$_follow_dnn/lib/dnn_node_example/example" ]]; then
  echo 'Official isolated perception dependencies are missing' >&2
  return 1
fi
export AMENT_PREFIX_PATH="$_follow_fusion:$_follow_dnn:$AMENT_PREFIX_PATH"
export LD_LIBRARY_PATH="$_follow_fusion/lib:$_follow_dnn/lib:$LD_LIBRARY_PATH"
export PYTHONPATH="$_follow_dnn/local/lib/python3.10/dist-packages:$PYTHONPATH"
unset _follow_fusion _follow_dnn
