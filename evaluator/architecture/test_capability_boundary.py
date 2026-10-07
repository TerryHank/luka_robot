from .source_checks import ROOT,executable_text,sources,imported_modules,tree


def test_capabilities_have_no_motion_or_motor_implementation():
    for path in sources(ROOT/'system/luka_capabilities'):
        text=executable_text(path.read_text(encoding='utf-8'))
        for token in ('Twist(', 'NavigateToPose', 'ddsm_car_control', 'RS485'):
            assert token not in text,f'{path}: {token}'
        assert not any(name=='serial' or name.startswith('serial.') for name in imported_modules(tree(path)))


def test_voice_actions_share_the_gateway_and_preserve_original_command():
    text=(ROOT/'visualization/console/nx_voice_gateway.py').read_text(encoding='utf-8')
    assert 'capability_execute(tool,body,command)' in text
    assert "path={'stop':'/api/nav/stop'" not in text
    assert 'Twist(' not in executable_text(text)
