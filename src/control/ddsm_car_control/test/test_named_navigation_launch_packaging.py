from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def test_unified_launch_starts_named_navigation_for_saved_map_modes():
    launch_source = (
        PACKAGE_ROOT / "launch" / "ddsm_bringup.launch.py"
    ).read_text(encoding="utf-8")

    assert '"enable_named_navigation"' in launch_source
    assert 'executable="named_navigation_server"' in launch_source
    assert '"/hotel/navigate_to_destination"' in launch_source
    assert '"/hotel/goal_destination"' in launch_source
    assert 'enabled_for_mode("enable_named_navigation", ["nav", "auto_nav"])' in launch_source


def test_ddsm_package_declares_semantic_map_runtime_dependency():
    package_source = (PACKAGE_ROOT / "package.xml").read_text(encoding="utf-8")

    assert "<exec_depend>hotel_semantic_map</exec_depend>" in package_source
