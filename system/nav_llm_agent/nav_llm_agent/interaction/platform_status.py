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
        self.create_timer(1.0, self.publish_status)

    def _seen(self, component, payload):
        self.last[component] = (time.monotonic(), payload)

    def _component(self, name):
        seen_at, payload = self.last[name]
        age = None if seen_at <= 0 else max(0.0, time.monotonic() - seen_at)
        return {
            "online": age is not None and age <= self.stale_sec,
            "age_sec": None if age is None else round(age, 3),
            "last": payload,
        }

    def publish_status(self):
        payload = {
            "schema": "luka.interaction.platform_status.v1",
            "architecture": "L4 Interaction Platform",
            "audio_frontend": os.getenv("LUKA_AUDIO_FRONTEND", "guarded"),
            "voice_backend": os.getenv("LUKA_VOICE_BACKEND", "legacy"),
            "xiaozhi_mode": os.getenv("LUKA_XIAOZHI_MODE", "mcp_only"),
            "components": {
                name: self._component(name) for name in self.last
            },
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
