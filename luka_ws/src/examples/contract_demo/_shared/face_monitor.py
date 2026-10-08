#!/usr/bin/env python3
"""Read-only YuNet/SFace reference demo, not identity authorization."""
import time
from pathlib import Path
import sys
import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image

WS = Path(__file__).resolve().parents[4]
from luka_face_identity.vision import FaceFeatures


class FaceMonitor(Node):
    def __init__(self):
        super().__init__("contract_demo_face_monitor")
        models = WS.parent / "luka_data/ml_models/person_follow"
        self.features = FaceFeatures(models / "yunet.onnx", models / "sface.onnx")
        self.reference = None
        self.last = 0.
        self.output = self.create_publisher(Image, "/contract_demo/face_image", 1)
        self.create_subscription(Image, "/camera/color/image_raw", self.frame, qos_profile_sensor_data)
        self.get_logger().info("First accepted face becomes a RAM-only reference.")

    def frame(self, message):
        if time.monotonic() - self.last < .4:
            return
        self.last = time.monotonic()
        if message.encoding not in ("rgb8", "bgr8"):
            self.get_logger().warning("Unsupported camera encoding: " + message.encoding)
            return
        try:
            image = np.frombuffer(bytes(message.data), np.uint8).reshape(message.height, message.step)
            image = image[:, :message.width * 3].reshape(message.height, message.width, 3).copy()
            if message.encoding == "rgb8":
                image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
            result = self.features.face_features(image, [0, 0, message.width, message.height])
            label = "FACE: " + result["reason"]
            if result["accepted"]:
                embedding = np.asarray(result["embedding"], np.float32).reshape(1, -1)
                if self.reference is None:
                    self.reference = embedding.copy()
                    label = "REFERENCE CAPTURED (RAM ONLY)"
                else:
                    score = self.features.recognizer.match(
                        self.reference, embedding, cv2.FaceRecognizerSF_FR_COSINE)
                    label = "REFERENCE SIMILARITY %.3f" % score
                if result["face_bbox"]:
                    x1, y1, x2, y2 = result["face_bbox"]
                    cv2.rectangle(image, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(image, label, (12, 28), cv2.FONT_HERSHEY_SIMPLEX, .6, (0, 220, 255), 2)
            cv2.putText(image, "NO AUTHORIZATION / NO NAVIGATION", (12, 52),
                        cv2.FONT_HERSHEY_SIMPLEX, .45, (0, 220, 255), 1)
            output = Image()
            output.header = message.header
            output.height, output.width = message.height, message.width
            output.encoding, output.step = "bgr8", message.width * 3
            output.data = image.tobytes()
            self.output.publish(output)
        except (ValueError, cv2.error) as error:
            self.get_logger().error(str(error))


def main():
    rclpy.init()
    node = FaceMonitor()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
