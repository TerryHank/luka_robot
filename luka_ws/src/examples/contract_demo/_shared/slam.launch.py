"""Existing slam_toolbox only: no legacy ESP32 or motion driver startup."""
from pathlib import Path
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from ament_index_python.packages import get_package_share_directory

WS = Path(__file__).resolve().parents[4]


def generate_launch_description():
    return LaunchDescription([IncludeLaunchDescription(
        PythonLaunchDescriptionSource(str(Path(get_package_share_directory("slam_toolbox")) /
                                           "launch/online_async_launch.py")),
        launch_arguments={
            "slam_params_file": str(WS / "src/control/ddsm_car_control/config/slam_toolbox_mapping.yaml"),
            "use_sim_time": "false", "autostart": "true", "use_lifecycle_manager": "false",
        }.items(),
    )])
