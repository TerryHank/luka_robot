import yaml
from .source_checks import ROOT


def parameters(name,node):
    return yaml.safe_load((ROOT/'common/config'/name).read_text(encoding='utf-8'))[node]['ros__parameters']


def test_gateway_output_goes_through_both_safety_stages_and_final_base_gate():
    guard=parameters('nx_heading_guard.yaml','lateral_escape_guard')
    monitor=parameters('nx_nav2.yaml','collision_monitor')
    base=parameters('nx_manual_base.yaml','/**')
    assert guard['cmd_vel_in_topic']=='/luka/motion/autonomy'
    assert guard['cmd_vel_out_topic']==monitor['cmd_vel_in_topic']=='/nx/nav_guarded'
    assert monitor['cmd_vel_out_topic']==base['nav_cmd_vel_topic']=='/nx/nav_safe'
    assert base['timeout']<=.25


def test_no_legacy_follow_velocity_subscription_can_bypass_collision_monitor():
    gate=(ROOT/'control/luka_base_gate/luka_base_gate/gate.py').read_text(encoding='utf-8')
    assert "'/nx/follow_safe'" not in gate and "'/nx/dashboard_follow_safe'" not in gate
    assert "self.create_subscription(Twist,'/nx/web_teleop_cmd_vel'" in gate
