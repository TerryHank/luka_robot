import importlib.util
import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import unittest
import urllib.error
import urllib.request

source=Path(__file__).parents[1]/'oellm_server/openai_server.py'
spec=importlib.util.spec_from_file_location('luka_oellm_contract',source)
server_module=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=server_module
spec.loader.exec_module(server_module)


class OellmContractTests(unittest.TestCase):
    def test_chatml_preserves_roles_and_history(self):
        messages=[{'role':'system','content':'你是露卡。'},
                  {'role':'user','content':'我叫小明。'},
                  {'role':'assistant','content':'你好，小明。'},
                  {'role':'user','content':'我叫什么名字？'}]
        system,prompt=server_module._messages_to_prompt(messages)
        self.assertIsNone(system)
        self.assertEqual(prompt,''.join('<|im_start|>'+m['role']+'\n'+m['content']+'<|im_end|>\n' for m in messages)+'<|im_start|>assistant\n')

    def test_unsupported_role_is_rejected(self):
        with self.assertRaises(ValueError):
            server_module._messages_to_prompt([{'role':'tool','content':'move'}])

    def test_http_model_and_message_contract(self):
        calls=[]
        def infer_chat(**fields):
            calls.append(fields)
            return '你叫小明。'
        cfg=SimpleNamespace(model_id='qwen2.5-1.5b-instruct-bpu')
        server=server_module._SingleThreadHTTPServer(('127.0.0.1',0),server_module.make_handler(SimpleNamespace(infer_chat=infer_chat),cfg))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            url='http://127.0.0.1:'+str(server.server_port)
            with urllib.request.urlopen(url+'/health') as response:self.assertEqual(json.load(response)['status'],'ok')
            payload={'model':cfg.model_id,'stream':False,'messages':[{'role':'user','content':'我叫什么名字？'}]}
            def request():
                return urllib.request.Request(url+'/v1/chat/completions',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
            with urllib.request.urlopen(request()) as response:
                self.assertEqual(json.load(response)['choices'][0]['message']['content'],'你叫小明。')
            self.assertEqual(calls[0]['messages'],payload['messages'])
            payload['model']='qwen3-4b-chat'
            with self.assertRaises(urllib.error.HTTPError) as failure:urllib.request.urlopen(request())
            self.assertEqual(failure.exception.code,400)
            self.assertEqual(len(calls),1)
        finally:server.shutdown();server.server_close();thread.join(timeout=3)
