from pathlib import Path

import yaml


PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def test_setup_installs_home_manager_console_script():
    setup_text = (PACKAGE_ROOT / "setup.py").read_text(encoding="utf-8")

    assert (
        "ddsm_home_manager = ddsm_car_control.ddsm_home_manager:main"
    ) in setup_text


def test_bringup_launch_exposes_home_manager_arguments_and_node():
    launch_text = (
        PACKAGE_ROOT / "launch" / "ddsm_bringup.launch.py"
    ).read_text(encoding="utf-8")

    assert '"enable_home_manager"' in launch_text
    assert 'default_value="auto"' in launch_text
    assert '"home_pose_file"' in launch_text
    assert "/home/sunrise/luka_ws/src/common/config/home_pose.yaml" in launch_text
    assert '"home_map_file"' in launch_text
    assert "executable=\"ddsm_home_manager\"" in launch_text
    assert (
        'condition=enabled_for_mode("enable_home_manager", ["nav", "auto_nav", "slam_nav"])'
        in launch_text
    )
    assert '"home_pose_file": LaunchConfiguration("home_pose_file")' in launch_text
    assert '"map_file": LaunchConfiguration("home_map_file")' in launch_text


def test_default_home_pose_template_is_safe_until_user_sets_home():
    config_path = PACKAGE_ROOT / "config" / "home_pose.yaml"
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))

    assert data["configured"] is False
    assert data["frame_id"] == "map"
    assert data["x"] == 0.0
    assert data["y"] == 0.0
    assert data["yaw"] == 0.0
    assert data["map_file"] == ""
    assert data["map_sha256"] == ""
