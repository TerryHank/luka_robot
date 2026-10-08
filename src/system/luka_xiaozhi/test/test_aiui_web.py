import base64
import hashlib
import hmac
import unittest
from urllib.parse import urlparse, parse_qs
from luka_xiaozhi.aiui_web import signed_url, text_request


class WebTests(unittest.TestCase):
    def test_official_signature(self):
        date='Thu, 08 Oct 2026 08:00:00 GMT'
        endpoint='wss://aiui.xf-yun.com/v3/aiint/sos'
        url=signed_url(endpoint,'example-key','example-secret',date)
        values=parse_qs(urlparse(url).query)
        auth=base64.b64decode(values['authorization'][0]).decode()
        raw='host: aiui.xf-yun.com\ndate: '+date+'\nGET /v3/aiint/sos HTTP/1.1'
        expected=base64.b64encode(hmac.new(b'example-secret',raw.encode(),hashlib.sha256).digest()).decode()
        self.assertIn('signature="'+expected+'"',auth)
        self.assertEqual(values['date'],[date])

    def test_credentials_not_sent_to_other_hosts_or_plaintext(self):
        for endpoint in ('ws://aiui.xf-yun.com/v3/aiint/sos','wss://other.example/v3/aiint/sos'):
            with self.assertRaises(ValueError): signed_url(endpoint,'test','test')

    def test_text_is_utf8_base64_and_request_ids_separate(self):
        one=text_request('test','device','你好','one','main',True)
        two=text_request('test','device','继续','two','main',False)
        self.assertEqual(base64.b64decode(one['payload']['text']['text']).decode(),'你好')
        self.assertNotEqual(one['header']['stmid'],two['header']['stmid'])
        self.assertFalse(two['parameter']['nlp']['new_session'])
