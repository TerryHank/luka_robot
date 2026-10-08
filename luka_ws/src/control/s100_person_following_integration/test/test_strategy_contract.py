"""Prevent falling back to C++ defaults instead of the pinned official launch contract."""
import json
from pathlib import Path
import yaml


def test_strategy_matches_pinned_official_launch_defaults():
    config=Path(__file__).parents[1]/'config'
    baseline=json.loads((config/'UPSTREAM.json').read_text())
    params=yaml.safe_load((config/'person_following_s100.yaml').read_text())['/**']['ros__parameters']
    for key,value in baseline['strategy_defaults'].items():
        assert params.get(key)==value,(key,value,params.get(key))
    assert params['output_mode']=='dry_run' and params['follow_enabled_on_start'] is False
    assert params['single_person_auto_relock'] is True
    assert params['spin_action_name']=='/spin'
    assert params['odometry_topic']=='/wheel/odom'
