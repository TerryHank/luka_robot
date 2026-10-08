"""Official AIUI cloud LLM WebSocket API; no ARM NLP-library dependency."""
import asyncio
import base64
from email.utils import formatdate
import hashlib
import hmac
import json
from pathlib import Path
import ssl
import time
from urllib.parse import urlencode, urlparse
import uuid


class CloudError(RuntimeError):
    def __init__(self, error_code):
        super().__init__('AIUI cloud request failed')
        self.error_code = int(error_code)


def signed_url(endpoint, key, secret, date=None):
    parsed = urlparse(endpoint)
    if parsed.scheme != 'wss' or parsed.netloc != 'aiui.xf-yun.com' or parsed.path not in ('/v2/aiint/ws', '/v3/aiint/sos'):
        raise ValueError('AIUI credentials may only be sent to its official WSS endpoint')
    date = date or formatdate(usegmt=True)
    source = f'host: {parsed.netloc}\ndate: {date}\nGET {parsed.path} HTTP/1.1'
    signature = base64.b64encode(hmac.new(secret.encode(), source.encode(), hashlib.sha256).digest()).decode()
    origin = f'api_key="{key}", algorithm="hmac-sha256", headers="host date request-line", signature="{signature}"'
    return endpoint + '?' + urlencode({'host':parsed.netloc, 'date':date,
                                      'authorization':base64.b64encode(origin.encode()).decode()})


def text_request(appid, sn, text, stmid, scene, new_session):
    return {'header':{'appid':appid, 'sn':sn, 'stmid':stmid, 'status':3,
                     'scene':scene, 'interact_mode':'oneshot'},
            'parameter':{'nlp':{'nlp':{'encoding':'utf8','compress':'raw','format':'json'},
                               'sub_scene':'cbm_v45','new_session':new_session}},
            'payload':{'text':{'encoding':'utf8','compress':'raw','format':'plain','status':3,
                              'text':base64.b64encode(text.encode()).decode()}}}


class CloudAiui:
    def __init__(self, config):
        self.config = config
        self.credentials = Path(config.get('aiui_config', '/home/sunrise/.config/luka_audio/aiui.cfg'))
        self.endpoint = config.get('aiui_cloud_endpoint', 'wss://aiui.xf-yun.com/v3/aiint/sos')
        self.new_session = True

    def available(self):
        try:
            if self.credentials.stat().st_mode & 0o077: return False
            login = json.loads(self.credentials.read_text())['login']
            return all(login.get(k) and not str(login[k]).startswith('YOUR_') for k in ('appid','key','api_secret'))
        except (OSError, KeyError, ValueError): return False

    async def request(self, text, cancel):
        import websockets
        cfg = json.loads(self.credentials.read_text()); login = cfg['login']
        secret = login['api_secret']
        url = signed_url(self.endpoint, login['key'], secret)
        stmid = uuid.uuid4().hex
        sn = Path('/etc/machine-id').read_text().strip()
        packet = text_request(login['appid'], sn, text, stmid,
            self.config.get('aiui_scene', cfg.get('global',{}).get('scene','main')), self.new_session)
        parts = {}; deadline = time.monotonic() + 30
        try:
            async with websockets.connect(url, ssl=ssl.create_default_context(), open_timeout=8,
                                          close_timeout=1, max_size=2*1024*1024) as ws:
                await ws.send(json.dumps(packet))
                while time.monotonic() < deadline:
                    if cancel.is_set(): raise InterruptedError('cancelled')
                    try: raw = await asyncio.wait_for(ws.recv(), timeout=.25)
                    except asyncio.TimeoutError: continue
                    frame = json.loads(raw); header = frame.get('header',{})
                    if header.get('stmid') not in (None, stmid): continue
                    if header.get('code',0): raise CloudError(header['code'])
                    payload = frame.get('payload',{})
                    if payload.get('nlp',{}).get('text'):
                        nlp = payload['nlp']
                        text_part = base64.b64decode(nlp['text']).decode('utf8')
                        intent = 0
                        if payload.get('cbm_meta',{}).get('text'):
                            meta = json.loads(base64.b64decode(payload['cbm_meta']['text']))
                            intent = meta.get('nlp',{}).get('intent',0)
                        elif frame.get('parameter',{}).get('nlp'):
                            intent = frame['parameter']['nlp'].get('loc',{}).get('intent',0)
                        parts[(int(intent),int(nlp.get('seq',0)))] = text_part
                        if sum(map(len,parts.values())) > 6000: raise CloudError(-2)
                    if header.get('status') == 2:
                        answer = ''.join(parts[key] for key in sorted(parts))
                        if not answer.strip(): raise CloudError(-3)
                        self.new_session = False
                        return [answer.strip()]
                raise TimeoutError('AIUI cloud reply timed out')
        except (CloudError, InterruptedError, TimeoutError): raise
        except Exception as exc:
            # Exception strings can contain a signed URL; never pass them to ROS.
            code = getattr(exc,'status_code',None)
            if code is None and getattr(exc,'response',None) is not None:
                code = exc.response.status_code
            raise CloudError(code or -1) from None

    def ask(self, text, cancel):
        return asyncio.run(self.request(text,cancel))
