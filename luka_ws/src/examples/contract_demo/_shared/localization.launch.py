"""Reuse existing map/AMCL configuration; odometry has one separate owner."""
from pathlib import Path
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

WS = Path(__file__).resolve().parents[4]


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument("map_yaml",default_value=str(WS.parent/"luka_data/maps/ddsm_map_floor_4.yaml")),
        Node(package="nav2_map_server", executable="map_server", name="map_server",
             parameters=[{"yaml_filename": LaunchConfiguration("map_yaml"),
                          "use_sim_time": False}], output="screen"),
        Node(package="nav2_amcl", executable="amcl", name="amcl",
             parameters=[str(WS / "src/control/ddsm_car_control/config/nav2_mecanum_mppi_params.yaml"),
                         {"set_initial_pose": False}], output="screen"),
        Node(package="nav2_lifecycle_manager", executable="lifecycle_manager",
             name="contract_demo_localization_manager",
             parameters=[{"autostart": True, "node_names": ["map_server", "amcl"]}], output="screen"),
    ])
