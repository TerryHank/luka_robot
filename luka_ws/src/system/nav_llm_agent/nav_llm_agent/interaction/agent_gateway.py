from __future__ import annotations

from collections import OrderedDict
import json
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from .envelope import dedup_key, normalize_envelope, public_envelope


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

    def _is_duplicate(self, env: dict) -> bool:
        now = time.monotonic()
        cutoff = now - self.dedup_window
        while self._recent:
            _, seen_at = next(iter(self._recent.items()))
            if seen_at >= cutoff:
                break
            self._recent.popitem(last=False)
        key = dedup_key(env)
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
        env = public_envelope(env)
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
