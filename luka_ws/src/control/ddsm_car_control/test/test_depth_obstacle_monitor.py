import math
from pathlib import Path
from types import SimpleNamespace

import yaml


PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def test_geometry_filters_floor_and_reports_nearest_corridor_obstacle():
    from ddsm_car_control.depth_geometry import select_obstacle_points

    translation = SimpleNamespace(x=0.0, y=0.0, z=0.0)
    rotation = SimpleNamespace(x=0.0, y=0.0, z=0.0, w=1.0)
    selected, nearest = select_obstacle_points(
        [(0.40, 0.05, 0.20), (0.25, 0.80, 0.30), (0.30, 0.0, -0.02)],
        translation,
        rotation,
        min_x=0.12,
        max_x=3.0,
        max_abs_y=2.0,
        min_z=0.05,
        max_z=1.2,
        corridor_half_width=0.30,
    )

    assert selected == [(0.40, 0.05, 0.20), (0.25, 0.80, 0.30)]
    assert math.isclose(nearest, 0.40)


def test_depth_projection_confirmation_and_lidar_fusion():
    from ddsm_car_control.depth_geometry import (
        confirm_depth_ranges,
        fuse_scan_ranges,
        project_points_to_scan,
    )

    translation = SimpleNamespace(x=0.0, y=0.0, z=0.0)
    rotation = SimpleNamespace(x=0.0, y=0.0, z=0.0, w=1.0)
    projected = project_points_to_scan(
        [(0.50, 0.0, 0.20), (0.80, 0.0, 0.30)],
        translation,
        rotation,
        angle_min=-0.2,
        angle_increment=0.1,
        beam_count=5,
        range_min=0.1,
        range_max=2.5,
    )
    confirmed = confirm_depth_ranges(
        projected,
        projected,
        distance_tolerance=0.20,
    )
    fused = fuse_scan_ranges([2.0] * 5, confirmed)

    assert math.isclose(projected[2], 0.50)
    assert math.isclose(fused[2], 0.50)
    assert fused[0] == 2.0


def test_active_nav_config_keeps_depth_obstacles_without_voxel_layer():
    for name in (
        "nav2_mecanum_mppi_params.yaml",
        "nav2_mecanum_mppi_omni_params.yaml",
    ):
        params = yaml.safe_load((PACKAGE_ROOT / "config" / name).read_text())
        local = params["local_costmap"]["local_costmap"]["ros__parameters"]
        global_costmap = params["global_costmap"]["global_costmap"]["ros__parameters"]
        assert "voxel_layer" not in local["plugins"]
        assert "voxel_layer" not in local
        for costmap in (local, global_costmap):
            layer = costmap["obstacle_layer"]
            assert layer["observation_sources"] == "scan depth_scan"
            assert layer["scan"]["topic"] == "/scan"
            assert (
                layer["depth_scan"]["topic"]
                == "/depth_camera/confirmed_obstacle_scan"
            )
            assert layer["depth_scan"]["marking"] is True
            assert layer["depth_scan"]["clearing"] is False
            assert layer["depth_scan"]["observation_persistence"] == 0.0
        assert params["amcl"]["ros__parameters"]["scan_topic"] == "/scan"
        assert local["inflation_layer"]["inflation_radius"] == 0.34
        assert global_costmap["inflation_layer"]["inflation_radius"] == 0.34
        assert (
            params["controller_server"]["ros__parameters"]["FollowPath"]
            ["ObstaclesCritic"]["collision_margin_distance"]
            == 0.10
        )
        assert (
            params["collision_monitor"]["ros__parameters"]["scan"]["topic"]
            == "/scan_obstacle_fused"
        )


def test_bringup_starts_monitor_with_depth_camera():
    text = (PACKAGE_ROOT / "launch" / "ddsm_bringup.launch.py").read_text()
    assert '"enable_point_cloud": False' in text
    assert 'name="depth_point_cloud_throttle"' not in text
    assert '"depth_image_topic": "/camera/depth/image_raw"' in text
    assert '"camera_info_topic": "/camera/depth/camera_info"' in text
    assert '"scan_input_topic": "/scan"' in text
    assert '"fused_scan_topic": "/scan_obstacle_fused"' in text
    assert '"depth_scan_topic": "/depth_camera/confirmed_obstacle_scan"' in text
    assert '"processing_rate": 12.0' in text
    assert '"depth_unit_scale": 0.001' in text
    assert '"depth_timeout": 0.5' in text
    assert '"memory_frame": "odom"' in text
    assert '"obstacle_memory_duration": 2.5' in text
    assert '"scan_topic": "/scan_obstacle_fused"' in text
    assert '"front_trigger_distance": 0.80' in text
    assert '"min_z": 0.05' in text
    assert '"max_z": 0.45' in text
    assert 'executable="depth_obstacle_monitor"' in text
    assert '"/depth_camera/nearest_obstacle_distance"' not in text


def test_monitor_publishes_timestamped_depth_only_scan():
    source = (
        PACKAGE_ROOT / "ddsm_car_control" / "depth_obstacle_monitor.py"
    ).read_text()
    assert '"depth_scan_topic", "/depth_camera/confirmed_obstacle_scan"' in source
    assert "depth_scan.header.stamp = stamp" in source
    assert "self.depth_scan_pub.publish(depth_scan)" in source
    assert "self._persistent_depth_cells" in source
    assert "self._remember_depth_ranges(" in source
    assert '"depth_image_topic", "/camera/depth/image_raw"' in source
    assert '"camera_info_topic", "/camera/depth/camera_info"' in source
    assert "PointCloud2" not in source
    assert "point_cloud2" not in source


def test_bringup_exposes_opt_in_colored_point_cloud():
    text = (PACKAGE_ROOT / "launch" / "ddsm_bringup.launch.py").read_text()
    assert '"enable_colored_point_cloud"' in text
    assert '"ENABLE_COLORED_POINT_CLOUD", default_value="false"' in text
    assert '"depth_registration": ParameterValue(' in text
    assert '"640 if \'"' in text
    assert '"480 if \'"' in text
    assert '"camera_color_optical_frame"' in text
    assert "/camera/depth_registered/points" in text


def test_guard_holds_stop_when_terminal_path_disallows_lateral_escape():
    source = (
        PACKAGE_ROOT / "ddsm_car_control" / "lateral_escape_guard.py"
    ).read_text()
    assert "if self.path_allows_escape():" in source
    assert 'self.enter_state("hold_stop")' in source
    assert "percentile(front_values, 0.05)" in source


def test_guard_only_chooses_a_side_with_clear_margin():
    source = (
        PACKAGE_ROOT / "ddsm_car_control" / "lateral_escape_guard.py"
    ).read_text()
    assert "if max(left_score, right_score) < min_clearance:" in source
    assert "if abs(left_score - right_score) < min_advantage:" in source
    assert "return 1.0 if left_score > right_score else -1.0" in source


def test_guard_rechecks_target_side_and_cools_down_after_escape():
    source = (
        PACKAGE_ROOT / "ddsm_car_control" / "lateral_escape_guard.py"
    ).read_text()
    assert "target_clearance = left if self.escape_side > 0.0 else right" in source
    assert "target_clearance < self.escape_side_stop_distance" in source
    assert "now - self.last_escape_finished < self.escape_cooldown_duration" in source
