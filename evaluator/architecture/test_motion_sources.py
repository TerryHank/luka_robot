import ast

from .source_checks import ROOT, sources, tree, twist_publishers


CONSOLE_TWIST_SOURCES = {
    "behavior/luka_behaviors/luka_behaviors/follow_controller.py": ["/nx/follow_safe"],
    "behavior/luka_behaviors/luka_behaviors/relocalization.py": ["/nx/nav_guarded"],
    "visualization/console/nx_escape_recovery.py": ["/nx/web_teleop_cmd_vel"],
    "visualization/console/web_teleop_dashboard.py": ["/nx/web_teleop_cmd_vel"],
    "visualization/console/mecanum_dance_demo.py": ["topic"],
    "visualization/console/person_follow_demo.py": ["args.cmd_topic"],
    "visualization/console/person_follow_node.py": ["/cmd_vel_nav"],
}


def test_existing_console_motion_sources_are_explicitly_inventoried():
    found = {}
    for path in [*sources(ROOT / "visualization/console"),*sources(ROOT / "behavior")]:
        topics = twist_publishers(tree(path))
        if topics:
            found[path.relative_to(ROOT).as_posix()] = topics
    assert found == CONSOLE_TWIST_SOURCES, f"Review a changed or new motion source: {found}"


def test_nav2_and_official_follow_keep_current_safety_ingress():
    nav = (ROOT / "system/bringup/nx_navigation.launch.py").read_text(encoding="utf-8")
    assert "('cmd_vel','/nx/nav_raw')" in nav
    assert "('cmd_vel_smoothed','/nx/nav_smoothed')" in nav
    follow = (ROOT / "control/luka_person_following/launch/selected_follow.launch.py").read_text(encoding="utf-8")
    assert "else '/nx/nav_smoothed'" in follow
    assert "else '/cmd_vel'" not in follow
    assert "default_value='true'" in follow
    guard = (ROOT / "common/config/nx_heading_guard.yaml").read_text(encoding="utf-8")
    assert "cmd_vel_in_topic: /nx/nav_smoothed" in guard
    assert "cmd_vel_out_topic: /nx/nav_guarded" in guard
    for name in ("nx_nav2.yaml", "nx_nav2_without_sonar.yaml"):
        monitor = (ROOT / "common/config" / name).read_text(encoding="utf-8")
        assert "cmd_vel_in_topic: /nx/nav_guarded" in monitor
        assert "cmd_vel_out_topic: /nx/nav_safe" in monitor
    base = (ROOT / "common/config/nx_manual_base.yaml").read_text(encoding="utf-8")
    assert "nav_cmd_vel_topic: /nx/nav_safe" in base
    manual = (ROOT / "visualization/console/nx_manual_base.py").read_text(encoding="utf-8")
    assert "'/nx/follow_safe',self.on_follow_cmd_vel" in manual
    assert "'/nx/web_teleop_cmd_vel',self.on_web_cmd_vel" in manual


def test_publisher_inspector_detects_aliases_and_keyword_topics():
    parsed = ast.parse("from geometry_msgs.msg import Twist as Velocity\n"
                       "node.create_publisher(msg_type=Velocity, topic='/cmd_vel', qos_profile=10)")
    assert twist_publishers(parsed) == ["/cmd_vel"]
