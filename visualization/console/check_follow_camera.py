"""Read one camera frame and benchmark detection without motion publishers."""
import time
import cv2
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CompressedImage
from person_follow_node import PersonFollow

rclpy.init()
node = Node('check_follow_camera_readonly')
frames = []
sub = node.create_subscription(CompressedImage, '/camera/color/image_raw/compressed',
                               lambda msg: frames.append((time.monotonic(), bytes(msg.data))) if not frames else None,
                               qos_profile_sensor_data)
deadline = time.monotonic() + 8
while not frames and time.monotonic() < deadline:
    rclpy.spin_once(node, timeout_sec=0.2)
if not frames:
    raise RuntimeError('No camera frame within 8 seconds')
cv2.setNumThreads(1)
class Detector:
    hog = cv2.HOGDescriptor()
Detector.hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
started = time.monotonic()
_, box = PersonFollow.detect(Detector(), frames[0])
print({'detector_ms': round((time.monotonic()-started)*1000), 'single_person_detected': box is not None})
node.destroy_node()
rclpy.shutdown()
