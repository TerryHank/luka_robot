import json
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'visualization/console'))
import nx_assistant_tools as legacy
from luka_capabilities.direct_router import direct, candidate, polite_command
from luka_capabilities.policy import validate


def test_pure_routing_matches_frozen_phase0_outputs():
    rows=json.loads((ROOT/'evaluator/fixtures/capabilities_phase0.json').read_text(encoding='utf-8'))
    for row in rows:
        text=row['text']
        assert direct(text)==legacy.direct(text)==row['direct']
        assert candidate(text)==legacy.candidate(text)==row['candidate']
        assert polite_command(text)==legacy.polite_command(text)==row['polite']


def test_grounding_and_negative_motion_requests_remain_rejected():
    validate('navigate', {'name':'厨房'}, '去厨房')
    for tool, args, text in [('navigate',{'name':'卧室'},'去厨房'),
                            ('follow_start',{},'你会跟随吗'),
                            ('navigate',{'name':'厨房'},'不要去厨房'),
                            ('music_volume',{'volume':90},'音量设置30')]:
        with pytest.raises(ValueError):validate(tool,args,text)
