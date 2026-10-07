from .source_checks import ROOT


def test_canonical_launch_files_exist_and_share_one_mission_behavior_host():
    folder=ROOT/'system/luka_bringup/launch'
    for name in ('hardware','sensing','localization','perception','navigation','motion_safety','behavior','mission','interaction','robot'):
        assert (folder/(name+'.launch.py')).is_file()
    text=(folder/'robot.launch.py').read_text(encoding='utf-8')
    assert "include('mission')" in text and "include('behavior')" not in text
    assert "SetEnvironmentVariable('LUKA_XIAOZHI_ALLOW_MOTION','0')" in text
    assert 'nx_readonly_odom' not in (folder/'localization.launch.py').read_text(encoding='utf-8')


def test_old_navigation_entrypoint_wraps_canonical_actions():
    text=(ROOT/'system/bringup/nx_navigation.launch.py').read_text(encoding='utf-8')
    assert 'safety_actions()+navigation_actions()' in text
