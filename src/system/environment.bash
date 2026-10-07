# Luka workspace environment only; this does not start robot services.
_LUKA_ENV_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export LUKA_WS="${LUKA_WS:-$(cd "$_LUKA_ENV_DIR/../.." && pwd)}"
export LUKA_DATA="${LUKA_DATA:-$HOME/luka_data}"
export LUKA_MAPS_DIR="${LUKA_MAPS_DIR:-$LUKA_DATA/maps}"
export LUKA_MODELS_DIR="${LUKA_MODELS_DIR:-$LUKA_DATA/ml_models}"
export LUKA_RECORDINGS_DIR="${LUKA_RECORDINGS_DIR:-$LUKA_DATA/recordings}"
export LUKA_BAGS_DIR="${LUKA_BAGS_DIR:-$LUKA_RECORDINGS_DIR/bags}"

source /opt/ros/humble/setup.bash
if [ -f "$LUKA_WS/install/local_setup.bash" ]; then
  source "$LUKA_WS/install/local_setup.bash"
fi

export DDSM_WS="$LUKA_WS"
export ROS_DOMAIN_ID=87 ROS_LOCALHOST_ONLY=1
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI="file://$LUKA_WS/src/common/config/cyclonedds_offline.xml"
unset _LUKA_ENV_DIR
