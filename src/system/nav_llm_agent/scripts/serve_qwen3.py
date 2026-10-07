#!/usr/bin/env python3
"""Ollama-compatible /api/chat server for local Qwen3-1.7B (transformers + CUDA)."""

from __future__ import annotations

import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer


class Qwen3Engine:
    def __init__(self, model_path: str, device: str):
        self.tokenizer = AutoTokenizer.from_pretrained(model_path)
        dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32
        self.model = AutoModelForCausalLM.from_pretrained(
            model_path,
            torch_dtype=dtype,
            device_map='auto' if device == 'auto' else None,
            attn_implementation='sdpa',
        )
        if device != 'auto' and not torch.cuda.is_available():
            self.model = self.model.to(device)
        self.model.eval()
        self.device = self.model.device

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_new_tokens: int,
        think: bool,
    ) -> str:
        text = self.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=think,
        )
        inputs = self.tokenizer([text], return_tensors='pt').to(self.device)
        do_sample = temperature > 0
        with torch.inference_mode():
            output_ids = self.model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=do_sample,
                temperature=max(temperature, 1e-5) if do_sample else None,
                top_p=0.8 if do_sample else None,
                top_k=20 if do_sample else None,
            )
        new_tokens = output_ids[0][inputs.input_ids.shape[1]:].tolist()
        try:
            think_end = 151668  # </think>
            index = len(new_tokens) - new_tokens[::-1].index(think_end)
        except ValueError:
            index = 0
        content = self.tokenizer.decode(
            new_tokens[index:], skip_special_tokens=True).strip()
        return content


ENGINE: Qwen3Engine | None = None
MODEL_NAME = 'qwen3:1.7b'


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:
        print(f'[qwen3-serve] {self.address_string()} {fmt % args}', flush=True)

    def _send_json(self, code: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path in ('/', '/api/tags', '/api/version'):
            self._send_json(200, {
                'models': [{'name': MODEL_NAME, 'model': MODEL_NAME}],
                'version': 'qwen3-local-compat',
            })
            return
        self._send_json(404, {'error': 'not found'})

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get('Content-Length') or '0')
        raw = self.rfile.read(length) if length else b'{}'
        try:
            req = json.loads(raw.decode('utf-8') or '{}')
        except json.JSONDecodeError:
            self._send_json(400, {'error': 'invalid json'})
            return

        if self.path not in ('/api/chat', '/v1/chat/completions'):
            self._send_json(404, {'error': f'unsupported path {self.path}'})
            return

        messages = req.get('messages') or []
        options = req.get('options') or {}
        temperature = float(
            options.get('temperature', req.get('temperature', 0.3)))
        think = bool(req.get('think', False))
        max_new_tokens = int(options.get('num_predict', 256))
        assert ENGINE is not None
        content = ENGINE.chat(messages, temperature, max_new_tokens, think)

        if self.path == '/v1/chat/completions':
            self._send_json(200, {
                'id': 'qwen3-local',
                'object': 'chat.completion',
                'model': req.get('model') or MODEL_NAME,
                'choices': [{
                    'index': 0,
                    'message': {'role': 'assistant', 'content': content},
                    'finish_reason': 'stop',
                }],
            })
            return

        self._send_json(200, {
            'model': req.get('model') or MODEL_NAME,
            'message': {'role': 'assistant', 'content': content},
            'done': True,
        })


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--model-path', required=True)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=11434)
    parser.add_argument('--device', default='auto')
    args = parser.parse_args()

    global ENGINE
    print(f'[qwen3-serve] loading {args.model_path}', flush=True)
    ENGINE = Qwen3Engine(args.model_path, args.device)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f'[qwen3-serve] listening on http://{args.host}:{args.port}', flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
