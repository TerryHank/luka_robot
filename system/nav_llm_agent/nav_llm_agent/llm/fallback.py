"""Ordered backend fallback without any action execution."""
from .base import LLMBackend


class FallbackBackend(LLMBackend):
    name = "fallback"

    def __init__(self, backends):
        self.backends = list(backends)
        if not self.backends:
            raise ValueError("at least one LLM backend is required")
        self.last_backend = None
        self.last_errors = []

    def generate(self, messages, tools=None):
        self.last_errors = []
        for backend in self.backends:
            try:
                result = backend.generate(messages, tools=tools)
                self.last_backend = backend.name
                return result
            except Exception as exc:
                self.last_errors.append((backend.name, type(exc).__name__))
        raise RuntimeError(
            "all LLM backends failed: "
            + ", ".join(f"{name}:{kind}" for name, kind in self.last_errors)
        )

    def stream_generate(self, messages, on_sentence, tools=None):
        self.last_errors = []
        for backend in self.backends:
            try:
                result = backend.stream_generate(
                    messages, on_sentence, tools=tools)
                self.last_backend = backend.name
                return result
            except Exception as exc:
                self.last_errors.append((backend.name, type(exc).__name__))
        raise RuntimeError(
            "all LLM backends failed: "
            + ", ".join(f"{name}:{kind}" for name, kind in self.last_errors)
        )
