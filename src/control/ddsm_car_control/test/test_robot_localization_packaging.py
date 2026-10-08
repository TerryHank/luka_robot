from pathlib import Path

import yaml


PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def test_robot_bringup_routes_raw_wheel_odom_through_robot_localization():
    bringup_text = (PACKAGE_ROOT / "launch" / "ddsm_robot_bringup.launch.py").read_text(
        encoding="utf-8"
    )

    assert 'package="robot_localization"' in bringup_text
    assert 'executable="ekf_node"' in bringup_text
    assert '"ekf_imu_yaw_rate.yaml"' in bringup_text
    assert '"publish_tf": "false"' in bringup_text
    assert '"odom_topic": "wheel/odom"' in bringup_text


def test_robot_bringup_can_switch_imu_heading_between_relative_and_absolute():
    bringup_text = (PACKAGE_ROOT / "launch" / "ddsm_robot_bringup.launch.py").read_text(
        encoding="utf-8"
    )

    assert '"imu_heading_mode"' in bringup_text
    assert 'default_value="relative"' in bringup_text
    assert '"imu0_relative": ParameterValue(' in bringup_text
    assert 'LaunchConfiguration("imu_heading_mode")' in bringup_text
    assert "'relative'" in bringup_text


def test_robot_bringup_starts_hwt906_imu_driver():
    bringup_text = (PACKAGE_ROOT / "launch" / "ddsm_robot_bringup.launch.py").read_text(
        encoding="utf-8"
    )

    assert 'executable="wit_imu_node"' in bringup_text
    assert '"imu_baud"' in bringup_text
    assert '"921600"' in bringup_text
    assert '"imu_topic": LaunchConfiguration("imu_topic")' in bringup_text


def test_robot_bringup_components_can_be_toggled_by_launch_args():
    bringup_text = (PACKAGE_ROOT / "launch" / "ddsm_robot_bringup.launch.py").read_text(
        encoding="utf-8"
    )

    assert "enable_base_driver" in bringup_text
    assert "enable_imu" in bringup_text
    assert "enable_ekf" in bringup_text
    assert "enable_lidar" in bringup_text
    assert "enable_laser_tf" in bringup_text
    assert 'condition=IfCondition(LaunchConfiguration("enable_base_driver"))' in bringup_text
    assert 'condition=IfCondition(LaunchConfiguration("enable_imu"))' in bringup_text
    assert 'condition=IfCondition(LaunchConfiguration("enable_ekf"))' in bringup_text
    assert 'condition=IfCondition(LaunchConfiguration("enable_lidar"))' in bringup_text
    assert 'condition=IfCondition(LaunchConfiguration("enable_laser_tf"))' in bringup_text


def test_ddsm_car_launch_can_disable_raw_odom_tf_and_remap_odom_topic():
    car_launch_text = (PACKAGE_ROOT / "launch" / "ddsm_car.launch.py").read_text(
        encoding="utf-8"
    )
    zdt_launch_text = (PACKAGE_ROOT / "launch" / "zdt_y42_mecanum.launch.py").read_text(
        encoding="utf-8"
    )

    assert '"publish_tf"' in car_launch_text
    assert '"odom_topic"' in car_launch_text
    assert '"odom_topic": LaunchConfiguration("odom_topic")' in car_launch_text
    assert "remappings" in zdt_launch_text
    assert '("odom", LaunchConfiguration("odom_topic"))' in zdt_launch_text


def test_ekf_config_uses_official_planar_robot_localization_frames():
    config = yaml.safe_load((PACKAGE_ROOT / "config" / "ekf.yaml").read_text())
    params = config["ekf_filter_node"]["ros__parameters"]

    assert params["two_d_mode"] is True
    assert params["map_frame"] == "map"
    assert params["odom_frame"] == "odom"
    assert params["base_link_frame"] == "base_link"
    assert params["world_frame"] == "odom"
    assert params["publish_tf"] is True
    assert params["frequency"] == 8.0
    assert params["odom0"] == "/wheel/odom"
    assert params["odom0_relative"] is True
    assert params["odom0_config"] == [
        True,
        True,
        False,
        False,
        False,
        True,
        True,
        True,
        False,
        False,
        False,
        True,
        False,
        False,
        False,
    ]


def test_ekf_imu_config_uses_stable_wheel_velocity_and_hwt906_heading_fusion():
    config = yaml.safe_load((PACKAGE_ROOT / "config" / "ekf_imu.yaml").read_text())
    params = config["ekf_filter_node"]["ros__parameters"]

    assert params["frequency"] == 10.0
    assert params["sensor_timeout"] == 0.3
    assert params["two_d_mode"] is True
    assert params["transform_time_offset"] == 0.05
    assert params["transform_timeout"] == 0.1
    assert params["print_diagnostics"] is True
    assert params["base_link_frame"] == "base_link"
    assert params["world_frame"] == "odom"

    assert params["odom0"] == "/wheel/odom"
    assert params["odom0_relative"] is True
    assert params["odom0_nodelay"] is True
    assert params["odom0_queue_size"] == 10
    assert params["odom0_config"] == [
        False,
        False,
        False,
        False,
        False,
        False,
        True,
        True,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
    ]

    assert params["imu0"] == "/imu/data"
    assert params["imu0_relative"] is True
    assert params["imu0_nodelay"] is True
    assert params["imu0_queue_size"] == 20
    assert params["imu0_config"] == [
        False,
        False,
        False,
        False,
        False,
        True,
        False,
        False,
        False,
        False,
        False,
        True,
        False,
        False,
        False,
    ]
    assert params["imu0_remove_gravitational_acceleration"] is True

    bringup_text = (PACKAGE_ROOT / "launch" / "ddsm_robot_bringup.launch.py").read_text(
        encoding="utf-8"
    )
    assert "'ekf_imu_yaw_rate.yaml' not in '" in bringup_text
    assert params["publish_acceleration"] is False
    assert params["use_control"] is False


def test_teacher_ekf_backup_keeps_wheel_pose_fusion_available_but_not_default():
    default_config = yaml.safe_load((PACKAGE_ROOT / "config" / "ekf_imu.yaml").read_text())
    teacher_config = yaml.safe_load(
        (PACKAGE_ROOT / "config" / "ekf_imu_teacher.yaml").read_text()
    )
    default_params = default_config["ekf_filter_node"]["ros__parameters"]
    teacher_params = teacher_config["ekf_filter_node"]["ros__parameters"]

    assert default_params["odom0_config"][:6] == [
        False,
        False,
        False,
        False,
        False,
        False,
    ]
    assert teacher_params["frequency"] == 30.0
    assert teacher_params["sensor_timeout"] == 0.1
    assert teacher_params["odom0_config"] == [
        True,
        True,
        False,
        False,
        False,
        True,
        True,
        True,
        False,
        False,
        False,
        True,
        False,
        False,
        False,
    ]
    assert teacher_params["imu0_config"] == default_params["imu0_config"]


def test_slam_and_nav2_default_to_imu_ekf():
    slam_launch_text = (PACKAGE_ROOT / "launch" / "ddsm_slam.launch.py").read_text(
        encoding="utf-8"
    )
    nav2_launch_text = (PACKAGE_ROOT / "launch" / "ddsm_nav2.launch.py").read_text(
        encoding="utf-8"
    )

    assert '"ekf_imu_yaw_rate.yaml"' in slam_launch_text
    assert '"ekf_imu_yaw_rate.yaml"' in nav2_launch_text


def test_nav2_consumes_filtered_odometry_topic():
    params = yaml.safe_load((PACKAGE_ROOT / "config" / "nav2_params.yaml").read_text())

    assert params["bt_navigator"]["ros__parameters"]["odom_topic"] == "/odometry/filtered"
    assert params["velocity_smoother"]["ros__parameters"]["odom_topic"] == "/odometry/filtered"


def test_bridge_does_not_create_tf_broadcaster_when_tf_output_is_disabled():
    bridge_text = (
        PACKAGE_ROOT / "ddsm_car_control" / "udp_cmd_vel_bridge.py"
    ).read_text(encoding="utf-8")

    assert "self.tf_broadcaster = None" in bridge_text
    assert "if self.publish_tf:" in bridge_text
    assert "self.tf_broadcaster is not None" in bridge_text


def test_robot_bringup_defaults_to_yaw_rate_ekf_config():
    bringup_text = (PACKAGE_ROOT / "launch" / "ddsm_robot_bringup.launch.py").read_text(
        encoding="utf-8"
    )
    unified_text = (PACKAGE_ROOT / "launch" / "ddsm_bringup.launch.py").read_text(
        encoding="utf-8"
    )

    assert '"ekf_imu_yaw_rate.yaml"' in bringup_text
    assert '"ekf_imu_yaw_rate.yaml"' in unified_text


def test_ekf_imu_yaw_rate_config_uses_wheel_velocity_and_imu_gyro_only():
    config = yaml.safe_load(
        (PACKAGE_ROOT / "config" / "ekf_imu_yaw_rate.yaml").read_text()
    )
    params = config["ekf_filter_node"]["ros__parameters"]

    assert params["frequency"] == 8.0
    assert params["transform_time_offset"] == 0.10
    assert params["odom0"] == "/wheel/odom"
    assert params["odom0_config"] == [
        False,
        False,
        False,
        False,
        False,
        False,
        True,
        True,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
    ]
    assert params["imu0"] == "/imu/data"
    assert params["imu0_config"] == [
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        True,
        False,
        False,
        False,
    ]
    assert params["imu0_relative"] is False
    assert params["imu0_remove_gravitational_acceleration"] is True

def test_base_driver_launch_defaults_speed_limit_to_03_mps():
    for relpath in [
        "launch/ddsm_robot_bringup.launch.py",
        "launch/ddsm_car.launch.py",
    ]:
        launch_text = (PACKAGE_ROOT / relpath).read_text(encoding="utf-8")

        assert '"max_linear_speed"' in launch_text
        assert 'default_value="0.3"' in launch_text

def test_unified_bringup_exposes_zdt_feedback_odometry_controls():
    robot_text = (PACKAGE_ROOT / "launch" / "ddsm_robot_bringup.launch.py").read_text(
        encoding="utf-8"
    )
    unified_text = (PACKAGE_ROOT / "launch" / "ddsm_bringup.launch.py").read_text(
        encoding="utf-8"
    )
    script_text = (PACKAGE_ROOT.parent.parent / "system/bringup/restart_nav_reset.sh").read_text(
        encoding="utf-8"
    )

    for name in ["feedback_enabled", "read_speed_feedback", "feedback_freq"]:
        assert f'"{name}"' in robot_text
        assert f'"{name}"' in unified_text
        assert f'"{name}": LaunchConfiguration("{name}")' in robot_text

    assert "FEEDBACK_ENABLED" in script_text
    assert "READ_SPEED_FEEDBACK" in script_text
    assert "FEEDBACK_FREQ" in script_text
    assert "feedback_enabled:='$FEEDBACK_ENABLED'" in script_text
    assert "read_speed_feedback:='$READ_SPEED_FEEDBACK'" in script_text
    assert "feedback_freq:='$FEEDBACK_FREQ'" in script_text

def test_zdt_bridge_direct_start_defaults_match_current_motor_direction_wiring():
    bridge_text = (
        PACKAGE_ROOT / "ddsm_car_control" / "zdt_mecanum_rs485_bridge.py"
    ).read_text(encoding="utf-8")

    expected_defaults = {
        "motor_direction_1": 1,
        "motor_direction_2": -1,
        "motor_direction_3": 1,
        "motor_direction_4": -1,
    }
    assert 'self.declare_parameter("motor_ids", [1, 2, 3, 4])' in bridge_text
    assert 'self.declare_parameter("mecanum_angular_direction", -1)' in bridge_text
    for name, value in expected_defaults.items():
        assert f'self.declare_parameter("{name}", {value})' in bridge_text


def test_zdt_base_launch_defaults_match_current_motor_direction_wiring():
    car_text = (PACKAGE_ROOT / "launch" / "ddsm_car.launch.py").read_text(
        encoding="utf-8"
    )
    zdt_text = (PACKAGE_ROOT / "launch" / "zdt_y42_mecanum.launch.py").read_text(
        encoding="utf-8"
    )

    expected_defaults = {
        "motor_direction_1": "1",
        "motor_direction_2": "-1",
        "motor_direction_3": "1",
        "motor_direction_4": "-1",
    }
    assert 'default_value="[1, 2, 3, 4]"' in car_text
    assert 'default_value="[1, 2, 3, 4]"' in zdt_text
    for name, value in expected_defaults.items():
        assert f'"{name}"' in car_text
        assert f'"{name}"' in zdt_text
        assert f'"{name}",\n        default_value="{value}"' in car_text
        assert f'"{name}",\n        default_value="{value}"' in zdt_text
        assert f'"{name}": LaunchConfiguration("{name}")' in car_text
