from __future__ import annotations

import json
import os
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import String


class InteractionPlatformStatus(Node):
    """Read-only L4 platform heartbeat and freshness summary."""

    def __init__(self):
        super().__init__("interaction_platform_status")
        self.stale_sec = max(
            1.0, float(self.declare_parameter("stale_sec", 5.0).value)
        )
        qos = QoSProfile(depth=10)
        qos.reliability = ReliabilityPolicy.RELIABLE
        qos.durability = DurabilityPolicy.TRANSIENT_LOCAL
        self.publisher = self.create_publisher(
            String, "/luka/interaction/platform_status", qos
        )
        self.last = {
            "voice_runtime": (0.0, None),
            "agent_gateway": (0.0, None),
            "agent": (0.0, None),
        }
        self.create_subscription(
            String, "/voice/runtime",
            lambda msg: self._seen("voice_runtime", msg.data), 10
        )
        self.create_subscription(
            String, "/luka/interaction/gateway_status",
            lambda msg: self._seen("agent_gateway", msg.data), 10
        )
        self.create_subscription(
            String, "/llm_status",
            lambda msg: self._seen("agent", msg.data), 10
        )
        self.xiaozhi_mode_file = str(
            self.declare_parameter(
                "xiaozhi_mode_file",
                f"/run/user/{os.getuid()}/luka/xiaozhi_mode",
            ).value
        )
        self.create_timer(1.0, self.publish_status)

    def _seen(self, component, payload):
        self.last[component] = (time.monotonic(), payload)

    def _decode(self, payload):
        if not payload:
            return None
        try:
            value = json.loads(payload)
            return value if isinstance(value, dict) else payload
        except (TypeError, json.JSONDecodeError):
            return payload

    def _component(self, name, node_names, expected_nodes=()):
        seen_at, raw = self.last[name]
        age = None if seen_at <= 0 else max(0.0, time.monotonic() - seen_at)
        node_online = any(node in node_names for node in expected_nodes)
        return {
            "online": node_online or (age is not None and age <= self.stale_sec),
            "node_online": node_online,
            "age_sec": None if age is None else round(age, 3),
            "last": self._decode(raw),
        }

    def _xiaozhi_mode(self):
        try:
            with open(self.xiaozhi_mode_file, encoding="utf-8") as stream:
                value = stream.read().strip()
                if value:
                    return value
        except OSError:
            pass
        return "off"

    def publish_status(self):
        node_names = set(self.get_node_names())
        components = {
            "voice_runtime": self._component(
                "voice_runtime", node_names,
                ("voice_gateway", "drobotics_voice_suite_bridge"),
            ),
            "agent_gateway": self._component(
                "agent_gateway", node_names, ("interaction_agent_gateway",),
            ),
            "agent": self._component(
                "agent", node_names, ("nav_llm_agent",),
            ),
        }
        voice = components["voice_runtime"].get("last")
        frontend = (
            voice.get("frontend", {}) if isinstance(voice, dict) else {}
        )
        speech = (
            voice.get("speech_backend", {}) if isinstance(voice, dict) else {}
        )
        payload = {
            "schema": "luka.interaction.platform_status.v1",
            "architecture": "L4 Interaction Platform",
            "audio_frontend": frontend.get("profile", "unknown"),
            "duplex_mode": frontend.get("duplex_mode", "unknown"),
            "aec_provider": frontend.get("aec_provider", "unknown"),
            "ns_provider": frontend.get("ns_provider", "unknown"),
            "speech_backend": speech.get("name", "unknown"),
            "xiaozhi_mode": self._xiaozhi_mode(),
            "components": components,
            "timestamp": time.time(),
        }
        self.publisher.publish(
            String(data=json.dumps(payload, ensure_ascii=False, sort_keys=True))
        )


def main(args=None):
    rclpy.init(args=args)
    node = InteractionPlatformStatus()
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
