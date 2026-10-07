from __future__ import annotations

from collections import OrderedDict
import json
import time
import uuid

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


SCHEMA = "luka.interaction.text.v1"
ALLOWED_SOURCES = {
    "voice_local",
    "voice_drobotics",
    "xiaozhi_protocol",
    "app",
    "dashboard",
    "legacy_voice",
}


def normalize_envelope(raw: str, default_source: str = "legacy_voice") -> dict:
    raw = str(raw or "").strip()
    if not raw:
        raise ValueError("empty interaction input")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        value = {"text": raw, "source": default_source}
    if not isinstance(value, dict):
        raise ValueError("interaction input must be text or a JSON object")

    text = str(value.get("text") or "").strip()
    if not 1 <= len(text) <= 1000:
        raise ValueError("interaction text must contain 1..1000 characters")
    source = str(value.get("source") or default_source).strip().lower()
    if source not in ALLOWED_SOURCES:
        raise ValueError(f"unsupported interaction source: {source}")

    captured_at = value.get("captured_at")
    if not isinstance(captured_at, (int, float)):
        captured_at = time.time()

    session_id = str(value.get("session_id") or "").strip()
    turn_id = str(value.get("turn_id") or "").strip()
    if not turn_id:
        turn_id = uuid.uuid4().hex

    result = {
        "schema": SCHEMA,
        "text": text,
        "source": source,
        "session_id": session_id,
        "turn_id": turn_id,
        "captured_at": float(captured_at),
    }
    if isinstance(value.get("speaker"), dict):
        result["speaker"] = value["speaker"]
    metadata = value.get("metadata")
    if isinstance(metadata, dict):
        # Interaction metadata is diagnostics/routing context only. Robot
        # capabilities must still be revalidated in L3.
        result["metadata"] = metadata
    return result


class InteractionAgentGateway(Node):
    """Single L4 -> L3 text ingress.

    This node never owns robot tools. It validates source/session/turn metadata,
    de-duplicates repeated transport delivery and forwards one normalized
    envelope to nav_llm_agent's existing voice-aware input.
    """

    def __init__(self):
        super().__init__("interaction_agent_gateway")
        self.input_topic = str(
            self.declare_parameter(
                "input_topic", "/luka/interaction/agent_input"
            ).value
        )
        self.output_topic = str(
            self.declare_parameter("output_topic", "/llm_voice_command").value
        )
        self.dedup_window = max(
            0.1, float(self.declare_parameter("dedup_window_sec", 1.0).value)
        )
        self.default_source = str(
            self.declare_parameter("default_source", "legacy_voice").value
        )
        self.publisher = self.create_publisher(String, self.output_topic, 20)
        self.status_pub = self.create_publisher(
            String, "/luka/interaction/gateway_status", 20
        )
        self.create_subscription(String, self.input_topic, self.on_input, 20)
        self._recent = OrderedDict()
        self._sequence = 0
        self.status("ready")

    def status(self, event: str, **details):
        payload = {
            "event": str(event),
            "input_topic": self.input_topic,
            "output_topic": self.output_topic,
            "sequence": self._sequence,
        }
        if details:
            payload["details"] = details
        self.status_pub.publish(
            String(data=json.dumps(payload, ensure_ascii=False, sort_keys=True))
        )

    def _dedup_key(self, env: dict) -> str:
        if env.get("turn_id"):
            return f"{env['source']}:{env.get('session_id','')}:{env['turn_id']}"
        return f"{env['source']}:{env.get('session_id','')}:{env['text']}"

    def _is_duplicate(self, env: dict) -> bool:
        now = time.monotonic()
        cutoff = now - self.dedup_window
        while self._recent:
            _, seen_at = next(iter(self._recent.items()))
            if seen_at >= cutoff:
                break
            self._recent.popitem(last=False)
        key = self._dedup_key(env)
        if key in self._recent:
            return True
        self._recent[key] = now
        if len(self._recent) > 256:
            self._recent.popitem(last=False)
        return False

    def on_input(self, msg: String):
        try:
            env = normalize_envelope(msg.data, self.default_source)
        except ValueError as exc:
            self.status("rejected", error=str(exc))
            return
        if self._is_duplicate(env):
            self.status(
                "duplicate_dropped",
                source=env["source"],
                turn_id=env["turn_id"],
            )
            return
        self._sequence += 1
        env["sequence"] = self._sequence
        env["received_at"] = time.time()
        self.publisher.publish(
            String(data=json.dumps(env, ensure_ascii=False, sort_keys=True))
        )
        self.status(
            "forwarded",
            source=env["source"],
            session_id=env["session_id"],
            turn_id=env["turn_id"],
        )


def main(args=None):
    rclpy.init(args=args)
    node = InteractionAgentGateway()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
