"""Adapter for the existing Ollama/OpenAI-compatible HTTP client."""
from __future__ import annotations

import json
import re
import urllib.request

from .base import LLMBackend


class OllamaBackend(LLMBackend):
    name = "ollama"

    def __init__(self, client):
        self.client = client

    def generate(self, messages, tools=None):
        del tools
        if self.client.api == "openai":
            path = (
                "/chat/completions"
                if self.client.base_url.endswith("/v1")
                else "/v1/chat/completions"
            )
            body = self.client._post(path, {
                "model": self.client.model,
                "messages": list(messages),
                "stream": False,
                "temperature": self.client.temperature,
                "max_tokens": self.client.max_tokens,
                "enable_thinking": False,
                "chat_template_kwargs": {"enable_thinking": False},
            })
            choices = body.get("choices") or []
            if not choices:
                raise RuntimeError("OpenAI-compatible empty choices")
            answer = (choices[0].get("message") or {}).get("content")
        else:
            body = self.client._post("/api/chat", {
                "model": self.client.model,
                "messages": list(messages),
                "stream": False,
                "think": False,
                "options": {
                    "temperature": self.client.temperature,
                    "num_ctx": self.client.num_ctx,
                },
            })
            answer = (body.get("message") or {}).get("content")
        if not isinstance(answer, str) or not answer.strip():
            raise RuntimeError("LLM backend returned empty content")
        return answer.strip()

    def stream_generate(self, messages, on_sentence, tools=None):
        del tools
        if self.client.api != "openai":
            return super().stream_generate(messages, on_sentence)
        path = (
            "/chat/completions"
            if self.client.base_url.endswith("/v1")
            else "/v1/chat/completions"
        )
        headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
        if self.client.api_key:
            headers["Authorization"] = "Bearer " + self.client.api_key
        payload = {
            "model": self.client.model,
            "messages": list(messages),
            "stream": True,
            "temperature": self.client.temperature,
            "max_tokens": self.client.max_tokens,
            "enable_thinking": False,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        request = urllib.request.Request(
            self.client.base_url + path,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        pending = ""
        spoken = []
        with urllib.request.urlopen(
            request, timeout=self.client.timeout_sec
        ) as response:
            for raw in response:
                line = raw.decode("utf-8").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                event = json.loads(data)
                if "error" in event:
                    raise RuntimeError(str(event["error"]))
                choices = event.get("choices") or []
                if not choices:
                    continue
                pending += choices[0].get("delta", {}).get("content") or ""
                while True:
                    match = re.search(r"[。！？!?]", pending)
                    if not spoken:
                        clause = next(
                            (
                                m for m in re.finditer(r"[，；：;:]", pending)
                                if len(pending[:m.start()].strip()) >= 8
                            ),
                            None,
                        )
                        if clause and (match is None or clause.end() < match.end()):
                            match = clause
                    if not match:
                        break
                    part = re.sub(r"\s+", " ", pending[:match.end()]).strip()
                    pending = pending[match.end():]
                    if part:
                        spoken.append(part)
                        on_sentence(part)
        tail = re.sub(r"\s+", " ", pending).strip()
        if tail:
            spoken.append(tail)
            on_sentence(tail)
        if not spoken:
            raise RuntimeError("LLM backend returned empty content")
        return "".join(spoken)
