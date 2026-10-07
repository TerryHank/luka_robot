import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'system/luka_capabilities'))
from luka_capabilities.dispatcher import CapabilityDispatcher


def dispatcher():
    mission=Mock();mission.active.return_value=False
    behavior=Mock();status=Mock();product=Mock()
    status.destinations.return_value=[{'id':'kitchen','display_name':'厨房'}]
    return CapabilityDispatcher(mission,behavior,status,Mock(),product)


def test_navigation_is_grounded_before_behavior_dispatch():
    d=dispatcher()
    assert '已提交' in d.execute('navigate',{'name':'厨房'},'去厨房')
    d.behavior_service.navigate.assert_called_once_with('kitchen')
    d.behavior_service.navigate.reset_mock()
    with pytest.raises(ValueError):d.execute('navigate',{'name':'厨房'},'不要去厨房')
    d.behavior_service.navigate.assert_not_called()


def test_stop_keeps_acquisition_follow_and_mission_cancellation():
    d=dispatcher();d.mission_service.stop.return_value={'message':'stopped'}
    assert d.execute('cancel_all',{},'停止')=='stopped'
    d.behavior_service.acquisition.cancel.assert_called_once()
    d.behavior_service.follow.stop.assert_called_once()
    d.mission_service.stop.assert_called_once()
