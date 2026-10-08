from .source_checks import ROOT,executable_text


def test_agent_does_not_own_nav2_action_creation():
    source=(ROOT/'system/nav_llm_agent/nav_llm_agent/agent_node.py').read_text(encoding='utf-8')
    text=executable_text(source)
    assert 'ActionClient(' not in text
    assert 'NavigateToPose' not in text
    assert 'from luka_capabilities import' in text
    assert '/api/assistant/execute' in text
    assert '旧版工具执行器已停用' in source
