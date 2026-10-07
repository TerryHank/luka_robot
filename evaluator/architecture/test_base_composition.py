import ast
from .source_checks import ROOT,tree


def test_base_uses_composition_and_replaces_ungated_driver_input_callbacks():
    path=ROOT/'control/luka_base_gate/luka_base_gate/gate.py'
    cls=next(node for node in tree(path).body if isinstance(node,ast.ClassDef) and node.name=='BaseGate')
    assert not cls.bases
    text=path.read_text(encoding='utf-8')
    assert 'create_driver()' in text
    assert 'destroy_subscription(self.driver.nav_cmd_sub)' not in text  # alias is self.nav_cmd_sub below
    assert 'destroy_subscription(self.nav_cmd_sub)' in text
    assert 'destroy_subscription(self.driver.manual_cmd_sub)' in text
    assert 'destroy_timer(self.driver.command_timer)' in text
    assert 'super()' not in text


def test_command_timer_keeps_encoder_scan_timeout_and_final_driver_boundary():
    text=(ROOT/'control/luka_base_gate/luka_base_gate/watchdog.py').read_text(encoding='utf-8')
    for required in ('feedback_at','scan_times','self.latest_manual_cmd=None','self.latest_nav_cmd=None','self.driver.on_command_timer()'):
        assert required in text
