"""Minimal LLM chat client: Ollama /api/chat or OpenAI-compatible /v1/chat/completions."""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from typing import Optional


class OllamaClient:
    """Supports api='ollama' (default) or api='openai' (llama.cpp / vLLM)."""

    def __init__(
        self,
        base_url: str,
        model: str,
        temperature: float,
        num_ctx: int,
        timeout_sec: float,
        think: bool = False,
        api: str = 'ollama',
        max_tokens: int = 128,
        api_key: Optional[str] = None,
    ):
        self.base_url = base_url.rstrip('/')
        self.model = model
        self.temperature = temperature
        self.num_ctx = num_ctx
        self.timeout_sec = timeout_sec
        self.think = think
        self.api = (api or 'ollama').strip().lower()
        self.max_tokens = max_tokens
        self.api_key = (api_key or '').strip()
        if self.api not in ('ollama', 'openai'):
            raise ValueError(f'unsupported api={api!r}; use ollama or openai')

    def chat(self, system_prompt: str, user_text: str) -> str:
        if self.api == 'openai':
            return self._chat_openai(system_prompt, user_text)
        return self._chat_ollama(system_prompt, user_text)

    def chat_first_sentence(self, system_prompt: str, user_text: str) -> str:
        """Voice-only SSE path; never used for tool or movement decisions.

        Return the first complete sentence and close the stream so the voice
        gateway can synthesize it without waiting for the entire completion.
        """
        if self.api != 'openai' or not self.model.startswith('qwen'):
            return self.chat(system_prompt, user_text)
        path = '/chat/completions' if self.base_url.endswith('/v1') else '/v1/chat/completions'
        payload = {'model': self.model,
                   'messages': [{'role': 'system', 'content': system_prompt},
                                {'role': 'user', 'content': user_text}],
                   'stream': True, 'enable_thinking': False,
                   'temperature': self.temperature, 'max_tokens': self.max_tokens}
        headers = {'Content-Type': 'application/json', 'Accept': 'text/event-stream'}
        if self.api_key:
            headers['Authorization'] = f'Bearer {self.api_key}'
        request = urllib.request.Request(self.base_url + path,
            data=json.dumps(payload).encode('utf-8'), headers=headers, method='POST')
        started = time.monotonic()
        content = ''
        with urllib.request.urlopen(request, timeout=self.timeout_sec) as response:
            for raw_line in response:
                if time.monotonic() - started > self.timeout_sec:
                    raise TimeoutError('voice response deadline exceeded')
                line = raw_line.decode('utf-8').strip()
                if not line.startswith('data:'):
                    continue
                data = line[5:].strip()
                if data == '[DONE]':
                    break
                chunk = json.loads(data)
                if chunk.get('error'):
                    raise RuntimeError('voice provider returned an error')
                choices = chunk.get('choices') or []
                if not choices:
                    continue
                token = (choices[0].get('delta') or {}).get('content')
                if not isinstance(token, str):
                    continue  # Never read reasoning_content aloud.
                content += token
                boundary = re.search(r'[。！？!?]', content)
                if boundary and content[:boundary.start()].strip():
                    return content[:boundary.end()].strip()
                if len(content) >= 48:
                    return content[:48].strip()
        if not content.strip():
            raise RuntimeError('voice provider returned no answer')
        return content.strip()

    def _post(self, path: str, payload: dict) -> dict:
        data = json.dumps(payload).encode('utf-8')
        headers = {'Content-Type': 'application/json'}
        if self.api_key:
            headers['Authorization'] = f'Bearer {self.api_key}'
        req = urllib.request.Request(
            f'{self.base_url}{path}',
            data=data,
            headers=headers,
            method='POST',
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except urllib.error.URLError as exc:
            raise RuntimeError(f'LLM request failed ({self.api}): {exc}') from exc

    def _chat_ollama(self, system_prompt: str, user_text: str) -> str:
        body = self._post('/api/chat', {
            'model': self.model,
            'messages': [
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_text},
            ],
            'stream': False,
            'think': self.think,
            'options': {
                'temperature': self.temperature,
                'num_ctx': self.num_ctx,
            },
        })
        message = body.get('message') or {}
        content = message.get('content')
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError(f'Ollama returned empty content: {body!r}')
        return content

    def _chat_openai(self, system_prompt: str, user_text: str) -> str:
        # llama.cpp is configured at its HTTP root, whereas DashScope's
        # OpenAI-compatible base URL already ends in /v1.
        path = '/chat/completions' if self.base_url.endswith('/v1') else '/v1/chat/completions'
        body = self._post(path, {
            'model': self.model,
            'messages': [
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_text},
            ],
            'stream': False,
            'enable_thinking': False,
            'chat_template_kwargs': {'enable_thinking': False},
            'temperature': self.temperature,
            'max_tokens': self.max_tokens,
        })
        choices = body.get('choices') or []
        if not choices:
            raise RuntimeError(f'OpenAI-compatible empty choices: {body!r}')
        message = choices[0].get('message') or {}
        content = message.get('content')
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError(f'OpenAI-compatible empty content: {body!r}')
        return content
