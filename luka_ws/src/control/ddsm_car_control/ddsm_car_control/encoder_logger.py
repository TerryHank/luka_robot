#!/usr/bin/env python3
import json
from typing import Any


def _as_int(value: Any, field_name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid integer field {field_name!r}: {value!r}") from exc


def _as_optional_int(value: Any, field_name: str) -> int | None:
    if value is None:
        return None
    return _as_int(value, field_name)


def extract_encoder_snapshot(data_chain_json: str) -> dict[str, Any]:
    data = json.loads(data_chain_json)
    odom = data.get("esp32_odom_udp_input", {})
    motor_feedback = data.get("motor_feedback_input", {})
    wheels = motor_feedback.get("wheels", [])
    if not isinstance(wheels, list):
        raise ValueError("motor_feedback_input.wheels must be a list")

    snapshot_wheels = []
    for wheel in wheels:
        snapshot_wheels.append(
            {
                "id": _as_int(wheel.get("id"), "id"),
                "valid": bool(wheel.get("valid", False)),
                "mode": _as_int(wheel.get("mode"), "mode"),
                "torque": _as_int(wheel.get("torque"), "torque"),
                "speed_rpm": _as_int(wheel.get("speed_rpm"), "speed_rpm"),
                "position": _as_int(wheel.get("position"), "position"),
                "total_encoder": _as_optional_int(
                    wheel.get("total_encoder"), "total_encoder"
                ),
                "error": _as_int(wheel.get("error"), "error"),
                "age_ms": _as_int(wheel.get("age_ms"), "age_ms"),
            }
        )

    return {
        "seq": _as_int(odom.get("seq"), "seq"),
        "stamp_ms": _as_int(odom.get("stamp_ms"), "stamp_ms"),
        "wheels": sorted(snapshot_wheels, key=lambda item: item["id"]),
    }


def format_encoder_snapshot(snapshot: dict[str, Any]) -> str:
    wheels = snapshot.get("wheels", [])
    wheel_text = []
    for wheel in wheels:
        total_text = ""
        if wheel.get("total_encoder") is not None:
            total_text = f" total={wheel['total_encoder']}"
        wheel_text.append(
            "wheel{id} pos={position}{total} rpm={speed_rpm} torque={torque} "
            "mode={mode} err={error} age={age_ms}ms valid={valid}".format(
                total=total_text, **wheel
            )
        )

    suffix = " | ".join(wheel_text) if wheel_text else "no wheel feedback"
    return (
        f"encoder snapshot seq={snapshot.get('seq')} "
        f"stamp_ms={snapshot.get('stamp_ms')} | {suffix}"
    )


def _load_ros():
    import rclpy
    from rclpy.node import Node
    from std_msgs.msg import String

    return rclpy, Node, String


def create_encoder_logger_node_class():
    _rclpy, Node, String = _load_ros()

    class EncoderLogger(Node):
        def __init__(self) -> None:
            super().__init__("encoder_logger")

            self.declare_parameter("input_topic", "ddsm/data_chain")
            self.declare_parameter("output_topic", "ddsm/encoder_snapshot")
            self.declare_parameter("period", 5.0)

            self.input_topic = self.get_parameter("input_topic").value
            self.output_topic = self.get_parameter("output_topic").value
            period = max(float(self.get_parameter("period").value), 0.1)

            self.latest_snapshot = None
            self.data_chain_sub = self.create_subscription(
                String, self.input_topic, self.on_data_chain, 10
            )
            self.snapshot_pub = self.create_publisher(String, self.output_topic, 10)
            self.timer = self.create_timer(period, self.on_timer)

            self.get_logger().info(
                f"encoder logger ready | input=/{self.input_topic} "
                f"output=/{self.output_topic} period={period:.2f}s"
            )

        def on_data_chain(self, msg) -> None:
            try:
                self.latest_snapshot = extract_encoder_snapshot(msg.data)
            except (json.JSONDecodeError, ValueError, KeyError, TypeError) as exc:
                self.get_logger().warn(
                    f"ignored bad encoder data_chain payload: {exc}",
                    throttle_duration_sec=2.0,
                )

        def on_timer(self) -> None:
            if self.latest_snapshot is None:
                self.get_logger().warn(
                    f"waiting for encoder feedback on /{self.input_topic}",
                    throttle_duration_sec=5.0,
                )
                return

            msg = String()
            msg.data = json.dumps(
                self.latest_snapshot, ensure_ascii=False, separators=(",", ":")
            )
            self.snapshot_pub.publish(msg)
            self.get_logger().info(format_encoder_snapshot(self.latest_snapshot))

    return EncoderLogger


def main(args=None) -> None:
    rclpy, _Node, _String = _load_ros()
    EncoderLogger = create_encoder_logger_node_class()

    rclpy.init(args=args)
    node = EncoderLogger()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
