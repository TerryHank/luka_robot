"""Existing task interfaces only; startup does not request patrol or Home."""
from pathlib import Path
from launch import LaunchDescription
from launch_ros.actions import Node

WS = Path(__file__).resolve().parents[4]
STATE = WS.parent / "luka_data/recordings/contract_demo/business"


def generate_launch_description():
    STATE.mkdir(parents=True, exist_ok=True)
    return LaunchDescription([
        Node(package="ddsm_car_control", executable="ddsm_home_manager", name="ddsm_home_manager",
             parameters=[{"home_pose_file": str(WS / "src/common/config/home_pose.yaml"),
                          "map_file": str(WS.parent / "luka_data/maps/ddsm_map_floor_4.yaml")}],
             output="screen"),
        Node(package="ddsm_car_control", executable="ddsm_patrol_manager", name="ddsm_patrol_manager",
             parameters=[{"route_file": str(WS / "src/common/config/patrol_route.yaml"),
                          "require_localization_ready": True}], output="screen"),
        Node(package="ddsm_car_control", executable="ddsm_mission_control", name="ddsm_mission_control",
             parameters=[{"state_file": str(STATE / "mission_state.yaml")}], output="screen"),
    ])
