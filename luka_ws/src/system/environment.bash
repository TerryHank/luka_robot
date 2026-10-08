# Luka workspace environment only; this does not start robot services.
source /opt/ros/humble/setup.bash
source /home/sunrise/luka_ws/install/local_setup.bash
export DDSM_WS=/home/sunrise/luka_ws
export ROS_DOMAIN_ID=87 ROS_LOCALHOST_ONLY=1
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI=file:///home/sunrise/luka_ws/src/common/config/cyclonedds_offline.xml
