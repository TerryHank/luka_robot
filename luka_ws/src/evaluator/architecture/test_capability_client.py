from unittest.mock import patch
import pytest
from luka_capabilities.client import execute_remote


def test_motion_client_fetches_current_generation_and_keeps_original_source():
    with patch('luka_capabilities.client.http',side_effect=[{'generation':7},{'ok':True}]) as http:
        execute_remote('navigate',{'name':'厨房'},'去厨房')
        assert http.call_args.args==('/api/assistant/execute',{
            'tool':'navigate','arguments':{'name':'厨房'},'source':'去厨房','generation':7})


def test_stop_does_not_depend_on_catalog_freshness():
    with patch('luka_capabilities.client.http',return_value={'ok':True}) as http:
        execute_remote('cancel_all',{},'停止')
        assert http.call_count==1 and http.call_args.args[0]=='/api/assistant/execute'


def test_client_rejects_invalid_motion_before_any_http_request():
    with patch('luka_capabilities.client.http') as http:
        with pytest.raises(ValueError):execute_remote('navigate',{'name':'厨房'},'不要去厨房')
        http.assert_not_called()
