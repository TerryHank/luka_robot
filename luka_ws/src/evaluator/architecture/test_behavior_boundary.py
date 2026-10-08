from .source_checks import ROOT,sources,tree,imported_modules,twist_publishers


def test_behavior_owns_nav2_and_only_publishes_autonomy_to_gateway_inputs():
    allowed={'/luka/motion/follow','/luka/motion/relocalize','/luka/motion/recovery'}
    for path in sources(ROOT/'behavior'):
        parsed=tree(path)
        for name in imported_modules(parsed):
            assert not name.startswith(('ddsm_car_control','serial')),f'{path}: {name}'
        for topic in twist_publishers(parsed):assert topic in allowed,f'{path}: {topic}'


def test_dashboard_keeps_an_adapter_and_does_not_create_nav2_goals():
    text=(ROOT/'visualization/console/nx_dashboard.py').read_text(encoding='utf-8')
    assert 'NavigateToPose' not in text
    assert 'ActionClient(' not in text
    assert 'create_dispatcher(self,destination_catalog,send_nav,self.music)' in text
    assert 'self.behaviors.initialize_recovery()' in text
