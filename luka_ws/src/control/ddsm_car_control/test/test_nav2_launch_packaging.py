from pathlib import Path
import re

import yaml


PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def test_ddsm_nav2_launch_starts_localization_before_navigation_autostart_gate():
    launch_file = PACKAGE_ROOT / "launch" / "ddsm_nav2.launch.py"
    text = launch_file.read_text(encoding="utf-8")

    assert "localization_launch.py" in text
    assert "navigation_launch.py" in text
    assert "nav_lifecycle_autostarter" in text
    assert "bringup_launch.py" not in text


def test_nav2_params_include_slam_toolbox_mapping_for_official_slam_mode():
    params = yaml.safe_load((PACKAGE_ROOT / "config" / "nav2_params.yaml").read_text())
    slam_params = params["slam_toolbox"]["ros__parameters"]

    assert slam_params["mode"] == "mapping"
    assert slam_params["map_frame"] == "map"
    assert slam_params["odom_frame"] == "odom"
    assert slam_params["base_frame"] == "base_link"
    assert slam_params["scan_topic"] == "/scan"
    assert slam_params["map_update_interval"] == 0.15
    assert slam_params["minimum_time_interval"] == 0.05
    assert slam_params["minimum_travel_distance"] == 0.05
    assert slam_params["minimum_travel_heading"] == 0.035


def test_amcl_transform_tolerance_is_low_latency_for_turning():
    params = yaml.safe_load((PACKAGE_ROOT / "config" / "nav2_params.yaml").read_text())
    amcl_params = params["amcl"]["ros__parameters"]

    assert amcl_params["transform_tolerance"] == 0.2
    assert amcl_params["update_min_d"] == 0.05
    assert amcl_params["update_min_a"] == 0.05
    assert amcl_params["pf_err"] == 0.03
    assert amcl_params["sigma_hit"] == 0.15


def test_mecanum_dwb_amcl_transform_tolerance_covers_scan_pipeline_lag():
    params = yaml.safe_load(
        (PACKAGE_ROOT / "config" / "nav2_mecanum_dwb_params.yaml").read_text()
    )
    amcl_params = params["amcl"]["ros__parameters"]

    assert amcl_params["transform_tolerance"] >= 1.0


def test_nav2_motion_limits_default_to_03_mps_navigation():
    params = yaml.safe_load((PACKAGE_ROOT / "config" / "nav2_params.yaml").read_text())
    controller = params["controller_server"]["ros__parameters"]["FollowPath"]
    smoother = params["velocity_smoother"]["ros__parameters"]

    assert controller["max_linear_vel"] == 0.3
    assert controller["min_linear_vel"] == 0.0
    assert controller["max_angular_vel"] == 1.0
    assert controller["min_angular_vel"] == -1.0
    assert controller["rotate_to_heading_angular_vel"] == 0.7
    assert controller["max_angular_accel"] == 1.4
    assert smoother["max_velocity"] == [0.3, 0.0, 1.0]
    assert smoother["min_velocity"] == [-0.12, 0.0, -1.0]
    assert smoother["max_accel"] == [0.25, 0.0, 1.4]
    assert smoother["max_decel"] == [-0.25, 0.0, -1.4]


def test_nav2_uses_smac_2d_global_planner_and_j1900_compatible_rpp_controller():
    params = yaml.safe_load((PACKAGE_ROOT / "config" / "nav2_params.yaml").read_text())

    planner = params["planner_server"]["ros__parameters"]
    grid_planner = planner["GridBased"]
    controller = params["controller_server"]["ros__parameters"]
    follow_path = controller["FollowPath"]

    assert planner["planner_plugins"] == ["GridBased"]
    assert grid_planner["plugin"] == "nav2_smac_planner::SmacPlanner2D"
    assert "lattice_filepath" not in grid_planner
    assert controller["controller_plugins"] == ["FollowPath"]
    assert (
        follow_path["plugin"]
        == "nav2_regulated_pure_pursuit_controller::RegulatedPurePursuitController"
    )
    assert follow_path["allow_reversing"] is False
    assert follow_path["use_rotate_to_heading"] is True


def test_lattice_experiment_keeps_default_nav2_params_unchanged():
    params = yaml.safe_load((PACKAGE_ROOT / "config" / "nav2_params.yaml").read_text())
    grid_planner = params["planner_server"]["ros__parameters"]["GridBased"]

    assert grid_planner["plugin"] == "nav2_smac_planner::SmacPlanner2D"
    assert "lattice_filepath" not in grid_planner


def test_lattice_experiment_uses_diff_smac_lattice_and_rpp():
    params = yaml.safe_load(
        (PACKAGE_ROOT / "config" / "nav2_lattice_params.yaml").read_text()
    )

    planner = params["planner_server"]["ros__parameters"]
    grid_planner = planner["GridBased"]
    follow_path = params["controller_server"]["ros__parameters"]["FollowPath"]

    assert planner["planner_plugins"] == ["GridBased"]
    assert grid_planner["plugin"] == "nav2_smac_planner::SmacPlannerLattice"
    assert (
        grid_planner["lattice_filepath"]
        == "/opt/ros/humble/share/nav2_smac_planner/sample_primitives/"
        "5cm_resolution/0.5m_turning_radius/diff/output.json"
    )
    assert grid_planner["tolerance"] <= 0.25
    assert grid_planner["allow_reverse_expansion"] is False
    assert grid_planner["goal_heading_mode"] == "DEFAULT"
    assert grid_planner["smooth_path"] is True
    assert grid_planner["cost_penalty"] >= 2.5
    assert grid_planner["rotation_penalty"] >= 4.0
    assert grid_planner["change_penalty"] >= 0.2
    assert grid_planner["non_straight_penalty"] >= 1.2
    assert (
        follow_path["plugin"]
        == "nav2_regulated_pure_pursuit_controller::RegulatedPurePursuitController"
    )
    assert follow_path["allow_reversing"] is False
    assert follow_path["use_rotate_to_heading"] is True


def test_lattice_experiment_keeps_hotel_robot_clearance_and_terminal_tolerances():
    params = yaml.safe_load(
        (PACKAGE_ROOT / "config" / "nav2_lattice_params.yaml").read_text()
    )

    local_inflation = params["local_costmap"]["local_costmap"]["ros__parameters"][
        "inflation_layer"
    ]
    global_inflation = params["global_costmap"]["global_costmap"]["ros__parameters"][
        "inflation_layer"
    ]
    goal_checker = params["controller_server"]["ros__parameters"][
        "general_goal_checker"
    ]

    assert local_inflation["inflation_radius"] >= 0.45
    assert global_inflation["inflation_radius"] >= 0.45
    assert goal_checker["xy_goal_tolerance"] >= 0.18
    assert goal_checker["yaw_goal_tolerance"] >= 0.30


def test_local_and_global_costmaps_keep_clearance_around_furniture():
    params = yaml.safe_load((PACKAGE_ROOT / "config" / "nav2_params.yaml").read_text())

    local_inflation = params["local_costmap"]["local_costmap"]["ros__parameters"][
        "inflation_layer"
    ]
    global_inflation = params["global_costmap"]["global_costmap"]["ros__parameters"][
        "inflation_layer"
    ]

    assert local_inflation["inflation_radius"] >= 0.60
    assert global_inflation["inflation_radius"] >= 0.60
    assert local_inflation["cost_scaling_factor"] <= 3.0
    assert global_inflation["cost_scaling_factor"] <= 3.0


def test_goal_checker_is_tightened_for_better_point_to_point_accuracy():
    params = yaml.safe_load((PACKAGE_ROOT / "config" / "nav2_params.yaml").read_text())
    controller = params["controller_server"]["ros__parameters"]
    progress_checker = controller["progress_checker"]
    goal_checker = controller["general_goal_checker"]

    assert progress_checker["required_movement_radius"] <= 0.03
    assert progress_checker["movement_time_allowance"] >= 45.0
    assert goal_checker["stateful"] is True
    assert goal_checker["xy_goal_tolerance"] == 0.10
    assert goal_checker["yaw_goal_tolerance"] == 0.25


def test_rpp_terminal_tracking_is_tuned_to_avoid_goal_oscillation():
    params = yaml.safe_load((PACKAGE_ROOT / "config" / "nav2_params.yaml").read_text())
    controller = params["controller_server"]["ros__parameters"]
    follow_path = controller["FollowPath"]

    assert controller["controller_frequency"] >= 8.0
    assert follow_path["lookahead_dist"] <= 0.4
    assert follow_path["min_lookahead_dist"] <= 0.25
    assert follow_path["max_lookahead_dist"] <= 0.65
    assert follow_path["lookahead_time"] <= 1.0
    assert follow_path["approach_velocity_scaling_dist"] >= 1.0
    assert follow_path["min_approach_linear_velocity"] <= 0.03
    assert follow_path["regulated_linear_scaling_min_speed"] <= 0.10
    assert follow_path["use_collision_detection"] is True
    assert follow_path["max_allowed_time_to_collision_up_to_carrot"] >= 0.6
    assert follow_path["rotate_to_heading_min_angle"] <= 0.55
    assert follow_path["allow_reversing"] is False


def test_smac_2d_planner_is_cost_aware_without_loose_goal_search():
    params = yaml.safe_load((PACKAGE_ROOT / "config" / "nav2_params.yaml").read_text())
    grid_planner = params["planner_server"]["ros__parameters"]["GridBased"]

    assert grid_planner["plugin"] == "nav2_smac_planner::SmacPlanner2D"
    assert grid_planner["tolerance"] <= 0.30
    assert grid_planner["allow_unknown"] is False
    assert grid_planner["cost_travel_multiplier"] >= 2.5
    assert grid_planner["smooth_path"] is True


def test_costmap_inflation_has_clearance_for_rectangular_hotel_robot():
    params = yaml.safe_load((PACKAGE_ROOT / "config" / "nav2_params.yaml").read_text())
    local_inflation = params["local_costmap"]["local_costmap"]["ros__parameters"][
        "inflation_layer"
    ]
    global_inflation = params["global_costmap"]["global_costmap"]["ros__parameters"][
        "inflation_layer"
    ]

    assert local_inflation["inflation_radius"] >= 0.45
    assert global_inflation["inflation_radius"] >= 0.45
    assert local_inflation["cost_scaling_factor"] <= 3.5
    assert global_inflation["cost_scaling_factor"] <= 3.5


def test_global_costmap_loads_lidar_obstacles_for_dynamic_replanning():
    params = yaml.safe_load((PACKAGE_ROOT / "config" / "nav2_params.yaml").read_text())
    global_params = params["global_costmap"]["global_costmap"]["ros__parameters"]
    obstacle_layer = global_params["obstacle_layer"]

    assert global_params["plugins"] == [
        "static_layer",
        "obstacle_layer",
        "inflation_layer",
    ]
    assert obstacle_layer["enabled"] is True
    assert obstacle_layer["observation_sources"] == "scan"
    assert obstacle_layer["scan"]["marking"] is True
    assert obstacle_layer["scan"]["clearing"] is True



def test_bt_replanning_is_slow_enough_to_not_churn_terminal_controller():
    tree = (
        PACKAGE_ROOT / "behavior_trees" / "ddsm_nav_to_pose_reversing_recovery.xml"
    ).read_text(encoding="utf-8")

    replanning_match = re.search(r'<RateController hz="([0-9.]+)">', tree)
    retry_match = re.search(r'<RecoveryNode number_of_retries="([0-9]+)"', tree)

    assert replanning_match is not None
    assert float(replanning_match.group(1)) <= 0.5
    assert retry_match is not None
    assert int(retry_match.group(1)) <= 4


def test_explore_lite_replans_slowly_enough_to_avoid_frontier_goal_churn():
    params = yaml.safe_load((PACKAGE_ROOT / "config" / "explore_lite.yaml").read_text())
    explore_params = params["/**"]["ros__parameters"]

    assert explore_params["planner_frequency"] == 0.3
    assert explore_params["progress_timeout"] >= 45.0
    assert explore_params["min_frontier_size"] >= 0.75
    assert explore_params["return_to_init"] is False


def test_slam_mapping_params_are_tuned_for_slow_manual_mapping():
    params = yaml.safe_load(
        (PACKAGE_ROOT / "config" / "slam_toolbox_mapping.yaml").read_text()
    )
    slam_params = params["slam_toolbox"]["ros__parameters"]

    assert slam_params["map_update_interval"] == 0.15
    assert slam_params["minimum_time_interval"] == 0.05
    assert slam_params["minimum_travel_distance"] == 0.05
    assert slam_params["minimum_travel_heading"] == 0.035
    assert slam_params["link_match_minimum_response_fine"] >= 0.2

def test_nav2_lifecycle_managers_have_generous_bond_timeout_for_slow_startup():
    params = yaml.safe_load((PACKAGE_ROOT / "config" / "nav2_params.yaml").read_text())

    assert params["lifecycle_manager_localization"]["ros__parameters"]["bond_timeout"] >= 10.0
    assert params["lifecycle_manager_navigation"]["ros__parameters"]["bond_timeout"] >= 10.0
