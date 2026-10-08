"""Backend-neutral text generation contract.

Backends return text only. They never receive ROS motion clients and never
publish cmd_vel/Nav2/DDSM commands.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class LLMBackend(ABC):
    name = "unknown"

    @abstractmethod
    def generate(self, messages, tools=None):
        raise NotImplementedError

    def stream_generate(self, messages, on_sentence, tools=None):
        text = self.generate(messages, tools=tools)
        if text:
            on_sentence(text)
        return text
