"""Synchronous adapter for D-Robotics ROS topic based LLM nodes."""
from __future__ import annotations

import threading
import time

from ai_msgs.msg import PerceptionTargets
from std_msgs.msg import String

from .base import LLMBackend


def format_prompt(messages):
    lines = []
    for item in messages or []:
        role = str(item.get("role") or "user").strip().lower()
        content = str(item.get("content") or "").strip()
        if content:
            lines.append(f"[{role}] {content}")
    return "\n".join(lines).strip()


def extract_result_text(msg):
    targets = getattr(msg, "targets", None) or []
    values = [str(getattr(target, "type", "") or "").strip() for target in targets]
    values = [value for value in values if value]
    return "\n".join(values).strip()


class RosTopicBackend(LLMBackend):
    def __init__(self, node, name, prompt_topic, result_topic, timeout_sec=12.0):
        self.name = str(name)
        self.node = node
        self.timeout_sec = float(timeout_sec)
        self.publisher = node.create_publisher(String, str(prompt_topic), 10)
        self._condition = threading.Condition()
        self._awaiting = False
        self._response = None
        self.subscription = node.create_subscription(
            PerceptionTargets, str(result_topic), self._on_result, 10)

    def _on_result(self, msg):
        text = extract_result_text(msg)
        if not text:
            return
        with self._condition:
            if not self._awaiting:
                return
            self._response = text
            self._awaiting = False
            self._condition.notify_all()

    def generate(self, messages, tools=None):
        del tools
        prompt = format_prompt(messages)
        if not prompt:
            raise ValueError("empty LLM prompt")
        deadline = time.monotonic() + self.timeout_sec
        with self._condition:
            self._response = None
            self._awaiting = True
            self.publisher.publish(String(data=prompt))
            while self._awaiting:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._awaiting = False
                    raise TimeoutError(f"{self.name} response timeout")
                self._condition.wait(timeout=min(.2, remaining))
            response = self._response
        if not response:
            raise RuntimeError(f"{self.name} returned empty content")
        return response
