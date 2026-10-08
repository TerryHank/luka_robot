"""Read-only filter demonstrations with separate outputs and no TF ownership."""
from pathlib import Path
import yaml
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

WS = Path(__file__).resolve().parents[4]


def nodes(context):
    mode = LaunchConfiguration("mode").perform(context)
    if mode == "ekf":
        path = WS / "src/control/ddsm_car_control/config/ekf_imu_yaw_rate.yaml"
        params = yaml.safe_load(path.read_text())["ekf_filter_node"]["ros__parameters"]
        params["publish_tf"] = False
        return [Node(package="robot_localization", executable="ekf_node",
                     name="ekf_filter_node", namespace="contract_demo",
                     parameters=[params], output="screen")]
    if mode == "deskew":
        return [Node(package="ddsm_car_control", executable="laser_scan_deskewer",
                     name="contract_demo_deskew", parameters=[{
                         "input_topic": "/scan", "output_topic": "/contract_demo/scan_deskewed",
                         "odom_topic": "/wheel/odom",
                     }], output="screen")]
    raise ValueError("mode must be ekf or deskew")


def generate_launch_description():
    return LaunchDescription([DeclareLaunchArgument("mode", default_value="ekf"),
                              OpaqueFunction(function=nodes)])
