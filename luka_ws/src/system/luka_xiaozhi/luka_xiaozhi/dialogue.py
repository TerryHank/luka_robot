"""XiaoZhi runs on S100; AIUI online and loopback LLM offline."""
import json
import re
import urllib.request
from urllib.parse import urlparse
from .aiui_web import CloudAiui, CloudError as AiuiError


def post_json(url, payload, timeout=60):
    request = urllib.request.Request(url, data=json.dumps(payload).encode('utf8'),
        headers={'Content-Type': 'application/json'}, method='POST')
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def spoken_text(answer):
    answer = re.sub(r'<think>.*?</think>', '', answer, flags=re.S)
    answer = re.sub(r'<think>.*$', '', answer, flags=re.S).strip()
    if not answer or answer.startswith(('{', '[')):
        raise RuntimeError('no answer safe for speech')
    return answer


class Dialogue:
    """Compatibility constructor; every real task delegates to the Moss owner."""
    def __init__(self, config, online=None, http=post_json, network=lambda: 'unknown', local_ready=lambda cancel: None):
        from .moss_client import MossDialogue
        self.client = MossDialogue(config, network, local_ready)

    def ask(self, text, cancel):
        return self.client.ask(text, cancel)

    def close(self):
        self.client.close()

    @property
    def cloud_state(self):
        return self.client.cloud_state

    @property
    def last_error_code(self):
        return self.client.last_error_code


def speech_chunks(text, limit=120):
    chunks, current = [], ''
    for part in re.findall(r'[^。！？!?\n]+[。！？!?\n]*|[。！？!?\n]+', text):
        while len(part) > limit:
            if current: chunks.append(current); current = ''
            chunks.append(part[:limit]); part = part[limit:]
        if len(current) + len(part) > limit: chunks.append(current); current = ''
        current += part
    if current: chunks.append(current)
    return [chunk.strip() for chunk in chunks if chunk.strip()]
