#!/usr/bin/env python3

import json
import math
import os
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
import rclpy
import yaml
from builtin_interfaces.msg import Duration
from nav_msgs.msg import OccupancyGrid
from rclpy.callback_groups import MutuallyExclusiveCallbackGroup
from rclpy.executors import MultiThreadedExecutor, ExternalShutdownException
from rclpy.duration import Duration as RclpyDuration
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import CameraInfo, Image, CompressedImage
from std_msgs.msg import String
from tf2_ros import Buffer, TransformException, TransformListener
from visualization_msgs.msg import Marker, MarkerArray

try:
    import onnxruntime as ort
except ImportError:
    ort = None

try:
    from rknnlite.api import RKNNLite
    from rknnlite.api.rknn_runtime import RKNNRuntime
except ImportError:
    RKNNLite = None
    RKNNRuntime = None

COCO_TARGETS = {
    "chair": "椅子",
    "couch": "沙发",
    "bed": "床",
    "dining table": "桌子",
    "toilet": "马桶",
    "tv": "电视",
    "sink": "洗手池",
    "refrigerator": "冰箱",
    "oven": "烤箱",
    "microwave": "微波炉",
    "potted plant": "盆栽",
    "clock": "时钟",
    "vase": "花瓶",
}

WORLD_CLASSES = [
    "door",
    "open door",
    "closed door",
    "window",
    "elevator door",
    "refrigerator",
    "chair",
    "sofa",
    "table",
    "bed",
    "toilet",
    "sink",
    "oven",
    "microwave",
    "television",
    "potted plant",
    "clock",
    "vase",
]

WORLD_CLASS_MAP = {
    "door": ("door", "门"),
    "open door": ("door", "门"),
    "closed door": ("door", "门"),
    "window": ("window", "窗户"),
    "elevator door": ("elevator_door", "电梯门"),
    "refrigerator": ("refrigerator", "冰箱"),
    "chair": ("chair", "椅子"),
    "sofa": ("couch", "沙发"),
    "table": ("dining table", "桌子"),
    "bed": ("bed", "床"),
    "toilet": ("toilet", "马桶"),
    "sink": ("sink", "洗手池"),
    "oven": ("oven", "烤箱"),
    "microwave": ("microwave", "微波炉"),
    "television": ("tv", "电视"),
    "potted plant": ("potted plant", "盆栽"),
    "clock": ("clock", "时钟"),
    "vase": ("vase", "花瓶"),
}

DOOR_CLASSES = {
    0: ("doorway", "门洞"),
    1: ("door", "门"),
    3: ("window", "窗户"),
}

ROOM_RULES = {
    "bedroom": ({"bed"}, "卧室候选"),
    "living_room": ({"couch"}, "客厅候选"),
    "bathroom": ({"toilet"}, "卫生间候选"),
    "kitchen": ({"refrigerator", "oven", "microwave"}, "厨房候选"),
    "dining_room": ({"dining table", "chair"}, "餐厅候选"),
}


def _map_origin_yaw(map_msg: OccupancyGrid) -> float:
    orientation = map_msg.info.origin.orientation
    return math.atan2(
        2.0 * (orientation.w * orientation.z + orientation.x * orientation.y),
        1.0 - 2.0 * (orientation.y * orientation.y + orientation.z * orientation.z),
    )


def _world_to_grid(map_msg: OccupancyGrid, x: float, y: float) -> Tuple[int, int]:
    origin = map_msg.info.origin.position
    yaw = _map_origin_yaw(map_msg)
    cos_yaw = math.cos(yaw)
    sin_yaw = math.sin(yaw)
    dx = x - float(origin.x)
    dy = y - float(origin.y)
    local_x = cos_yaw * dx + sin_yaw * dy
    local_y = -sin_yaw * dx + cos_yaw * dy
    resolution = float(map_msg.info.resolution)
    return int(math.floor(local_x / resolution)), int(math.floor(local_y / resolution))


def _cell_is_free(
    map_msg: OccupancyGrid, gx: int, gy: int, occupied_threshold: int = 50
) -> bool:
    width = int(map_msg.info.width)
    height = int(map_msg.info.height)
    if gx < 0 or gy < 0 or gx >= width or gy >= height:
        return False
    value = int(map_msg.data[gy * width + gx])
    return 0 <= value < occupied_threshold


def _pose_clearance(
    map_msg: OccupancyGrid,
    x: float,
    y: float,
    required_clearance: float,
    occupied_threshold: int = 50,
) -> float:
    resolution = float(map_msg.info.resolution)
    center_x, center_y = _world_to_grid(map_msg, x, y)
    search_clearance = required_clearance + 0.20
    cells = int(math.ceil(search_clearance / resolution))
    nearest = search_clearance
    for dy in range(-cells, cells + 1):
        for dx in range(-cells, cells + 1):
            distance = math.hypot(dx, dy) * resolution
            if distance > search_clearance:
                continue
            if not _cell_is_free(
                map_msg, center_x + dx, center_y + dy, occupied_threshold
            ):
                nearest = min(nearest, distance)
    return nearest


def find_safe_approach_pose(
    map_msg: OccupancyGrid,
    object_x: float,
    object_y: float,
    target_distance: float = 0.85,
    min_distance: float = 0.65,
    max_distance: float = 1.10,
    required_clearance: float = 0.42,
    occupied_threshold: int = 50,
) -> Optional[Tuple[float, float, float, float]]:
    """Return x, y, yaw and clearance for a free pose facing the object."""
    if not map_msg.data or map_msg.info.resolution <= 0.0:
        return None
    radii = np.arange(min_distance, max_distance + 0.001, 0.10)
    best = None
    best_score = -float("inf")
    for radius in radii:
        for angle_index in range(36):
            angle = angle_index * (2.0 * math.pi / 36.0)
            x = object_x + float(radius) * math.cos(angle)
            y = object_y + float(radius) * math.sin(angle)
            clearance = _pose_clearance(
                map_msg, x, y, required_clearance, occupied_threshold
            )
            if clearance + 1e-6 < required_clearance:
                continue
            score = clearance - 0.45 * abs(float(radius) - target_distance)
            if score > best_score:
                yaw = math.atan2(object_y - y, object_x - x)
                best = (x, y, yaw, clearance)
                best_score = score
    return best


@dataclass
class Detection:
    class_name: str
    display_name: str
    confidence: float
    box: Tuple[int, int, int, int]
    position: Optional[Tuple[float, float, float]] = None


@dataclass
class Candidate:
    class_name: str
    display_name: str
    positions: List[Tuple[float, float, float]] = field(default_factory=list)
    confidences: List[float] = field(default_factory=list)
    first_seen: float = 0.0
    last_seen: float = 0.0

    def add(self, position: Tuple[float, float, float], confidence: float, stamp: float):
        self.positions.append(position)
        self.confidences.append(confidence)
        self.positions = self.positions[-20:]
        self.confidences = self.confidences[-20:]
        if self.first_seen <= 0.0:
            self.first_seen = stamp
        self.last_seen = stamp

    @property
    def mean_position(self) -> Tuple[float, float, float]:
        values = np.asarray(self.positions, dtype=np.float64)
        mean = np.mean(values, axis=0)
        return float(mean[0]), float(mean[1]), float(mean[2])


class SemanticMappingRecorder(Node):
    def __init__(self):
        super().__init__("semantic_mapping_recorder")

        self.declare_parameter("color_topic", "/camera/color/image_raw")
        self.declare_parameter("use_compressed_color", True)
        self.declare_parameter("depth_topic", "/camera/depth/image_raw")
        self.declare_parameter("camera_info_topic", "/camera/color/camera_info")
        self.declare_parameter("map_frame", "map")
        self.declare_parameter("floor_id", "floor_1")
        self.declare_parameter("output_file", "")
        self.declare_parameter("enable_door_model", False)
        self.declare_parameter("door_model", "")
        self.declare_parameter(
            "furniture_model",
            "/home/sunrise/luka_ws/common/models/semantic/yolo11n.onnx",
        )
        self.declare_parameter(
            "furniture_fallback_model",
            "/home/sunrise/luka_ws/common/models/semantic/yolo11n.onnx",
        )
        self.declare_parameter(
            "rknn_runtime_library",
            "/home/sunrise/luka_ws/common/vendor/rknn-downloads/librknnrt.so",
        )
        self.declare_parameter("rknn_input_size", 320)
        self.declare_parameter("furniture_cfg", "")
        self.declare_parameter("furniture_weights", "")
        self.declare_parameter("coco_names", "")
        self.declare_parameter("inference_rate", 0.3)
        self.declare_parameter("preview_rate", 0.5)
        self.declare_parameter("publish_annotated_image", False)
        self.declare_parameter("preview_detection_hold", 3.0)
        self.declare_parameter("opencv_num_threads", 2)
        self.declare_parameter("confidence_threshold", 0.35)
        self.declare_parameter("doorway_confidence_threshold", 0.45)
        self.declare_parameter("door_confidence_threshold", 0.45)
        self.declare_parameter("window_confidence_threshold", 0.50)
        self.declare_parameter("confirm_observations", 8)
        self.declare_parameter("confirm_min_span", 3.0)
        self.declare_parameter("candidate_max_gap", 2.5)
        self.declare_parameter("structural_confirm_observations", 12)
        self.declare_parameter("structural_confirm_min_span", 5.0)
        self.declare_parameter("structural_max_position_stddev", 0.25)
        self.declare_parameter("merge_distance", 1.0)
        self.declare_parameter("max_depth", 6.0)
        self.declare_parameter("map_topic", "/map")
        self.declare_parameter("semantic_config_root", "~/ddsm_car_ws/config/semantic")
        self.declare_parameter("generate_object_waypoints", True)
        self.declare_parameter("approach_distance", 0.85)
        self.declare_parameter("approach_min_distance", 0.65)
        self.declare_parameter("approach_max_distance", 1.10)
        self.declare_parameter("waypoint_clearance", 0.42)
        self.declare_parameter("waypoint_refresh_interval", 5.0)
        self.declare_parameter("waypoint_excluded_classes", ["window"])

        self.color_topic = self.get_parameter("color_topic").value
        self.depth_topic = self.get_parameter("depth_topic").value
        self.info_topic = self.get_parameter("camera_info_topic").value
        self.map_frame = self.get_parameter("map_frame").value
        self.floor_id = self.get_parameter("floor_id").value
        output_file = self.get_parameter("output_file").value
        if not output_file:
            output_file = os.path.expanduser(
                f"~/ddsm_car_ws/config/semantic_auto/{self.floor_id}/detections.yaml"
            )
        self.output_file = Path(os.path.expanduser(output_file))
        self.rknn_input_size = int(self.get_parameter("rknn_input_size").value)
        cv2.setNumThreads(max(1, int(self.get_parameter("opencv_num_threads").value)))
        self.confidence_threshold = float(self.get_parameter("confidence_threshold").value)
        self.structural_confidence_thresholds = {
            "doorway": float(
                self.get_parameter("doorway_confidence_threshold").value
            ),
            "door": float(self.get_parameter("door_confidence_threshold").value),
            "window": float(
                self.get_parameter("window_confidence_threshold").value
            ),
        }
        self.confirm_observations = int(self.get_parameter("confirm_observations").value)
        self.confirm_min_span = float(self.get_parameter("confirm_min_span").value)
        self.candidate_max_gap = float(self.get_parameter("candidate_max_gap").value)
        self.structural_confirm_observations = int(
            self.get_parameter("structural_confirm_observations").value
        )
        self.structural_confirm_min_span = float(
            self.get_parameter("structural_confirm_min_span").value
        )
        self.structural_max_position_stddev = float(
            self.get_parameter("structural_max_position_stddev").value
        )
        self.merge_distance = float(self.get_parameter("merge_distance").value)
        self.max_depth = float(self.get_parameter("max_depth").value)
        self.map_topic = self.get_parameter("map_topic").value
        self.semantic_config_root = Path(
            os.path.expanduser(self.get_parameter("semantic_config_root").value)
        )
        self.generate_object_waypoints = bool(
            self.get_parameter("generate_object_waypoints").value
        )
        self.publish_annotated_image = bool(
            self.get_parameter("publish_annotated_image").value
        )
        self.approach_distance = float(self.get_parameter("approach_distance").value)
        self.approach_min_distance = float(
            self.get_parameter("approach_min_distance").value
        )
        self.approach_max_distance = float(
            self.get_parameter("approach_max_distance").value
        )
        self.waypoint_clearance = float(
            self.get_parameter("waypoint_clearance").value
        )
        self.waypoint_refresh_interval = float(
            self.get_parameter("waypoint_refresh_interval").value
        )
        self.waypoint_excluded_classes = {
            str(value)
            for value in self.get_parameter("waypoint_excluded_classes").value
        }

        sensor_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            reliability=ReliabilityPolicy.BEST_EFFORT,
        )
        annotated_image_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            reliability=ReliabilityPolicy.BEST_EFFORT,
        )
        marker_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        map_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.VOLATILE,
        )
        self.color_callback_group = MutuallyExclusiveCallbackGroup()
        self.depth_callback_group = MutuallyExclusiveCallbackGroup()
        self.info_callback_group = MutuallyExclusiveCallbackGroup()
        self.map_callback_group = MutuallyExclusiveCallbackGroup()
        self.processing_callback_group = MutuallyExclusiveCallbackGroup()
        self.preview_callback_group = MutuallyExclusiveCallbackGroup()
        self.sensor_qos = sensor_qos
        self.use_compressed_color = bool(self.get_parameter("use_compressed_color").value)
        self.color_subscription = None
        self.depth_subscription = None
        self.create_subscription(
            CameraInfo,
            self.info_topic,
            self._on_info,
            sensor_qos,
            callback_group=self.info_callback_group,
        )
        self.create_subscription(
            OccupancyGrid,
            self.map_topic,
            self._on_map,
            map_qos,
            callback_group=self.map_callback_group,
        )
        self.marker_pub = self.create_publisher(
            MarkerArray, "/semantic_mapping/markers", marker_qos
        )
        self.status_pub = self.create_publisher(String, "/semantic_mapping/status", 10)
        self.image_pub = self.create_publisher(
            Image, "/semantic_mapping/annotated_image", annotated_image_qos
        )

        self.tf_buffer = Buffer(cache_time=RclpyDuration(seconds=10.0))
        self.tf_listener = TransformListener(self.tf_buffer, self)
        self.lock = threading.Lock()
        self.inference_guard = threading.Lock()
        self.color_msg: Optional[Image] = None
        self.depth_msg: Optional[Image] = None
        self.info_msg: Optional[CameraInfo] = None
        self.candidates: List[Candidate] = []
        self.confirmed: List[Dict] = []
        self.map_msg: Optional[OccupancyGrid] = None
        self.preview_detections: List[Detection] = []
        self.preview_detection_time = 0.0
        self.last_waypoint_write = 0.0
        self.last_status = "starting"
        self.last_processed_pair = None
        self.inference_count = 0

        self.coco_names = self._load_names(self.get_parameter("coco_names").value)
        self.furniture_backend = "disabled"
        self.furniture_session = self._load_furniture_model()
        self.enable_door_model = bool(
            self.get_parameter("enable_door_model").value
        )
        if self.enable_door_model:
            self.door_session = self._load_door_model()
        else:
            self.door_session = None
            self.get_logger().info(
                "Door detector disabled; running single-model inference"
            )
        self._load_existing()

        rate = max(0.2, float(self.get_parameter("inference_rate").value))
        self.inference_period = 1.0 / rate
        self.next_capture_time = time.monotonic()
        # Keep subscription handles alive for the entire executor lifetime.
        # Destroying/recreating them inside a timer races queued DDS callbacks.
        self._enable_image_subscriptions()
        self.capture_timer = self.create_timer(
            0.25,
            self._capture_tick,
            callback_group=self.processing_callback_group,
        )
        preview_rate = max(0.5, float(self.get_parameter("preview_rate").value))
        self.preview_period = 1.0 / preview_rate
        self.last_preview_publish = 0.0
        self.preview_detection_hold = max(
            0.0, float(self.get_parameter("preview_detection_hold").value)
        )
        self.preview_timer = self.create_timer(
            self.preview_period,
            self._publish_preview,
            callback_group=self.preview_callback_group,
        )
        self.marker_timer = self.create_timer(
            2.0,
            self._publish_markers,
            callback_group=self.processing_callback_group,
        )
        self.get_logger().info(
            f"Semantic recorder ready: floor={self.floor_id}, output={self.output_file}"
        )

    def _load_names(self, path: str) -> List[str]:
        if not path or not os.path.isfile(path):
            self.get_logger().error(f"COCO class file not found: {path}")
            return []
        with open(path, "r", encoding="utf-8") as stream:
            return [line.strip() for line in stream if line.strip()]

    def _load_furniture_model(self):
        model = self.get_parameter("furniture_model").value
        if str(model).lower().endswith(".rknn"):
            session = self._load_furniture_rknn(model)
            if session is not None:
                return session
            fallback = self.get_parameter("furniture_fallback_model").value
            self.get_logger().warning(
                f"RKNN unavailable; falling back to ONNX model: {fallback}"
            )
            model = fallback
        if str(model).lower().endswith(".pt"):
            try:
                from ultralytics import YOLOWorld
            except Exception as exc:
                self.get_logger().error(
                    f"Cannot import YOLO-World; detector disabled: {exc}"
                )
                return None
            if not os.path.isfile(model):
                self.get_logger().error(f"YOLO-World model not found: {model}")
                return None
            try:
                session = YOLOWorld(model)
                session.set_classes(WORLD_CLASSES)
                self.furniture_backend = "world"
                self.get_logger().info(f"YOLO-World detector loaded: {model}")
                return session
            except Exception as exc:
                self.get_logger().error(f"Cannot load YOLO-World model: {exc}")
                return None
        if ort is None:
            self.get_logger().error(
                "onnxruntime is not installed; furniture detector disabled"
            )
            return None
        if not os.path.isfile(model):
            self.get_logger().error(f"Furniture model not found: {model}")
            return None
        try:
            options = ort.SessionOptions()
            options.intra_op_num_threads = 2
            options.inter_op_num_threads = 1
            options.add_session_config_entry("session.intra_op.allow_spinning", "0")
            options.add_session_config_entry("session.inter_op.allow_spinning", "0")
            session = ort.InferenceSession(
                model, sess_options=options, providers=["CPUExecutionProvider"]
            )
            self.furniture_backend = "onnx"
            self.get_logger().info(f"Furniture detector loaded: {model}")
            return session
        except Exception as exc:
            self.get_logger().error(f"Cannot load furniture model: {exc}")
            return None

    def _load_furniture_rknn(self, model: str):
        if RKNNLite is None or RKNNRuntime is None:
            self.get_logger().error(
                "rknn-toolkit-lite2 is not installed; RKNN detector unavailable"
            )
            return None
        if not os.path.isfile(model):
            self.get_logger().error(f"RKNN furniture model not found: {model}")
            return None
        runtime_library = self.get_parameter("rknn_runtime_library").value
        if runtime_library:
            if not os.path.isfile(runtime_library):
                self.get_logger().error(
                    f"RKNN runtime library not found: {runtime_library}"
                )
                return None
            RKNNRuntime._get_rknn_api_lib_path = (
                lambda _runtime, path=runtime_library: path
            )
        session = RKNNLite(verbose=False)
        try:
            if session.load_rknn(model) != 0:
                raise RuntimeError("load_rknn failed")
            if session.init_runtime(core_mask=RKNNLite.NPU_CORE_0_1_2) != 0:
                raise RuntimeError("init_runtime failed")
            self.furniture_backend = "rknn"
            self.get_logger().info(f"RKNN NPU furniture detector loaded: {model}")
            return session
        except Exception as exc:
            session.release()
            self.get_logger().error(f"Cannot load RKNN furniture model: {exc}")
            return None

    def _load_door_model(self):
        model = self.get_parameter("door_model").value
        if ort is None:
            self.get_logger().error("onnxruntime is not installed; door detector disabled")
            return None
        if not os.path.isfile(model):
            self.get_logger().error(f"Door model not found: {model}")
            return None
        try:
            options = ort.SessionOptions()
            options.intra_op_num_threads = 2
            options.inter_op_num_threads = 1
            options.add_session_config_entry("session.intra_op.allow_spinning", "0")
            options.add_session_config_entry("session.inter_op.allow_spinning", "0")
            return ort.InferenceSession(
                model, sess_options=options, providers=["CPUExecutionProvider"]
            )
        except Exception as exc:
            self.get_logger().error(f"Cannot load door model: {exc}")
            return None

    def _load_existing(self):
        if not self.output_file.is_file():
            return
        try:
            with self.output_file.open("r", encoding="utf-8") as stream:
                data = yaml.safe_load(stream) or {}
            self.confirmed = list(data.get("objects", []))
            self.get_logger().info(f"Loaded {len(self.confirmed)} existing auto objects")
        except Exception as exc:
            self.get_logger().warning(f"Cannot read existing semantic output: {exc}")

    def _on_color(self, msg: Image):
        with self.lock:
            self.color_msg = msg

    def _on_depth(self, msg: Image):
        with self.lock:
            self.depth_msg = msg

    def _enable_image_subscriptions(self):
        if self.color_subscription is None:
            self.color_subscription = self.create_subscription(
                CompressedImage if self.use_compressed_color else Image,
                self.color_topic.rstrip('/') + '/compressed' if self.use_compressed_color else self.color_topic,
                self._on_color,
                self.sensor_qos,
                callback_group=self.color_callback_group,
            )
        if self.depth_subscription is None:
            self.depth_subscription = self.create_subscription(
                Image,
                self.depth_topic,
                self._on_depth,
                self.sensor_qos,
                callback_group=self.depth_callback_group,
            )

    def _disable_image_subscriptions(self):
        if self.color_subscription is not None:
            self.destroy_subscription(self.color_subscription)
            self.color_subscription = None
        if self.depth_subscription is not None:
            self.destroy_subscription(self.depth_subscription)
            self.depth_subscription = None

    def _capture_tick(self):
        now = time.monotonic()
        if now < self.next_capture_time:
            return
        self.next_capture_time = now + self.inference_period
        self._process()

    def _on_info(self, msg: CameraInfo):
        with self.lock:
            self.info_msg = msg

    def _on_map(self, msg: OccupancyGrid):
        self.map_msg = msg
        now = time.monotonic()
        if (
            self.generate_object_waypoints
            and self.confirmed
            and now - self.last_waypoint_write >= self.waypoint_refresh_interval
        ):
            self._write_navigation_artifacts()
            self.last_waypoint_write = now

    @staticmethod
    def _color_array(msg: Image) -> np.ndarray:
        if isinstance(msg, CompressedImage):
            image = cv2.imdecode(np.frombuffer(msg.data, dtype=np.uint8), cv2.IMREAD_COLOR)
            if image is None:
                raise ValueError("Cannot decode compressed color image")
            return image
        channels = 3
        row = np.frombuffer(msg.data, dtype=np.uint8).reshape(msg.height, msg.step)
        image = row[:, : msg.width * channels].reshape(msg.height, msg.width, channels)
        if msg.encoding.lower() == "rgb8":
            return cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        return image.copy()

    @staticmethod
    def _depth_array(msg: Image) -> np.ndarray:
        dtype = np.dtype(">u2" if msg.is_bigendian else "<u2")
        row = np.frombuffer(msg.data, dtype=dtype).reshape(msg.height, msg.step // 2)
        return row[:, : msg.width].astype(np.uint16, copy=False)

    def _detect_furniture(self, image: np.ndarray) -> List[Detection]:
        if self.furniture_backend == "world":
            return self._detect_world(image)
        if self.furniture_session is None or not self.coco_names:
            return []
        height, width = image.shape[:2]
        if self.furniture_backend == "rknn":
            input_info = None
            model_size = self.rknn_input_size
        else:
            input_info = self.furniture_session.get_inputs()[0]
            model_size = input_info.shape[2]
            if not isinstance(model_size, int):
                model_size = 640
        prepared, scale, left, top = self._letterbox(image, size=model_size)
        rgb = cv2.cvtColor(prepared, cv2.COLOR_BGR2RGB)
        if self.furniture_backend == "rknn":
            outputs = self.furniture_session.inference(
                inputs=[rgb[None]], data_format=["nhwc"]
            )
            if not outputs:
                self.get_logger().warning("RKNN furniture inference failed")
                return []
            output = outputs[0]
        else:
            tensor = np.transpose(rgb.astype(np.float32) / 255.0, (2, 0, 1))[None]
            output = self.furniture_session.run(None, {input_info.name: tensor})[0]
        predictions = np.squeeze(output)
        if predictions.ndim != 2:
            self.get_logger().warning(
                f"Unexpected furniture model output shape: {output.shape}"
            )
            return []
        if predictions.shape[0] < predictions.shape[1]:
            predictions = predictions.T

        boxes, confidences, class_ids = [], [], []
        for row in predictions:
            if row.shape[0] == 6:
                x1, y1, x2, y2 = [float(value) for value in row[:4]]
                confidence = float(row[4])
                class_id = int(round(float(row[5])))
            else:
                scores = row[4:]
                class_id = int(np.argmax(scores))
                confidence = float(scores[class_id])
                cx, cy, bw, bh = [float(value) for value in row[:4]]
                x1, y1 = cx - bw / 2.0, cy - bh / 2.0
                x2, y2 = cx + bw / 2.0, cy + bh / 2.0
            if class_id >= len(self.coco_names):
                continue
            class_name = self.coco_names[class_id]
            if class_name not in COCO_TARGETS:
                continue
            if confidence < self.confidence_threshold:
                continue
            x1 = int(round((x1 - left) / scale))
            y1 = int(round((y1 - top) / scale))
            x2 = int(round((x2 - left) / scale))
            y2 = int(round((y2 - top) / scale))
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(width - 1, x2), min(height - 1, y2)
            if x2 <= x1 or y2 <= y1:
                continue
            boxes.append([x1, y1, x2 - x1, y2 - y1])
            confidences.append(confidence)
            class_ids.append(class_id)
        if not boxes:
            return []

        keep = []
        for class_id in sorted(set(class_ids)):
            class_indexes = [
                index for index, value in enumerate(class_ids) if value == class_id
            ]
            class_boxes = [boxes[index] for index in class_indexes]
            class_scores = [confidences[index] for index in class_indexes]
            selected = cv2.dnn.NMSBoxes(
                class_boxes, class_scores, self.confidence_threshold, 0.45
            )
            keep.extend(class_indexes[int(index)] for index in np.asarray(selected).reshape(-1))

        detections = []
        for index in keep:
            x, y, bw, bh = boxes[int(index)]
            class_name = self.coco_names[class_ids[int(index)]]
            detections.append(
                Detection(
                    class_name,
                    COCO_TARGETS[class_name],
                    float(confidences[int(index)]),
                    (max(0, x), max(0, y), min(width - 1, x + bw), min(height - 1, y + bh)),
                )
            )
        return detections

    def _detect_world(self, image: np.ndarray) -> List[Detection]:
        if self.furniture_session is None:
            return []
        try:
            results = self.furniture_session.predict(
                source=image,
                imgsz=640,
                conf=self.confidence_threshold,
                iou=0.45,
                device="cpu",
                verbose=False,
            )
        except Exception as exc:
            self.get_logger().error(f"YOLO-World inference failed: {exc}")
            return []
        if not results or results[0].boxes is None:
            return []

        result = results[0]
        names = result.names
        boxes = result.boxes.xyxy.cpu().numpy()
        confidences = result.boxes.conf.cpu().numpy()
        class_ids = result.boxes.cls.cpu().numpy().astype(np.int32)
        height, width = image.shape[:2]
        detections = []
        for box, confidence, class_id in zip(boxes, confidences, class_ids):
            prompt = str(names[int(class_id)]).strip().lower()
            mapped = WORLD_CLASS_MAP.get(prompt)
            if mapped is None:
                continue
            x1, y1, x2, y2 = [int(round(float(value))) for value in box]
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(width - 1, x2), min(height - 1, y2)
            if x2 <= x1 or y2 <= y1:
                continue
            class_name, display_name = mapped
            detections.append(
                Detection(
                    class_name=class_name,
                    display_name=display_name,
                    confidence=float(confidence),
                    box=(x1, y1, x2, y2),
                )
            )
        return detections

    @staticmethod
    def _letterbox(image: np.ndarray, size: int = 640):
        height, width = image.shape[:2]
        scale = min(size / width, size / height)
        new_width, new_height = int(round(width * scale)), int(round(height * scale))
        resized = cv2.resize(image, (new_width, new_height), interpolation=cv2.INTER_LINEAR)
        canvas = np.full((size, size, 3), 114, dtype=np.uint8)
        left = (size - new_width) // 2
        top = (size - new_height) // 2
        canvas[top : top + new_height, left : left + new_width] = resized
        return canvas, scale, left, top

    def _detect_doors(self, image: np.ndarray) -> List[Detection]:
        if self.door_session is None:
            return []
        height, width = image.shape[:2]
        model_size = 640
        prepared = cv2.resize(
            image, (model_size, model_size), interpolation=cv2.INTER_LINEAR
        )
        scale_x = width / float(model_size)
        scale_y = height / float(model_size)
        rgb = cv2.cvtColor(prepared, cv2.COLOR_BGR2RGB)
        tensor = np.transpose(rgb.astype(np.float32) / 255.0, (2, 0, 1))[None]
        output = self.door_session.run(["output0"], {"images": tensor})[0][0]
        boxes, scores, class_ids = [], [], []
        for row in output:
            confidence = float(row[4])
            class_id = int(round(float(row[5])))
            if class_id not in DOOR_CLASSES:
                continue
            class_name, _ = DOOR_CLASSES[class_id]
            if confidence < self.structural_confidence_thresholds[class_name]:
                continue
            x1, y1, x2, y2 = [float(value) for value in row[:4]]
            x1 = int(round(x1 * scale_x))
            y1 = int(round(y1 * scale_y))
            x2 = int(round(x2 * scale_x))
            y2 = int(round(y2 * scale_y))
            if x2 <= x1 or y2 <= y1:
                continue
            boxes.append([x1, y1, x2 - x1, y2 - y1])
            scores.append(confidence)
            class_ids.append(class_id)
        if not boxes:
            return []
        keep = cv2.dnn.NMSBoxes(boxes, scores, 0.0, 0.45)
        height, width = image.shape[:2]
        detections = []
        for index in np.asarray(keep).reshape(-1):
            x, y, bw, bh = boxes[int(index)]
            class_name, display_name = DOOR_CLASSES[class_ids[int(index)]]
            detections.append(
                Detection(
                    class_name,
                    display_name,
                    float(scores[int(index)]),
                    (max(0, x), max(0, y), min(width - 1, x + bw), min(height - 1, y + bh)),
                )
            )
        return detections

    def _position_from_depth(
        self, detection: Detection, depth: np.ndarray, info: CameraInfo
    ) -> Optional[Tuple[float, float, float]]:
        color_width = max(1, int(info.width))
        color_height = max(1, int(info.height))
        sx = depth.shape[1] / color_width
        sy = depth.shape[0] / color_height
        x1, y1, x2, y2 = detection.box
        u1 = max(0, int((x1 * 0.65 + x2 * 0.35) * sx))
        u2 = min(depth.shape[1], int((x1 * 0.35 + x2 * 0.65) * sx) + 1)
        v1 = max(0, int((y1 * 0.55 + y2 * 0.45) * sy))
        v2 = min(depth.shape[0], int((y1 * 0.35 + y2 * 0.65) * sy) + 1)
        if u2 <= u1 or v2 <= v1:
            return None
        values = depth[v1:v2, u1:u2]
        values = values[(values > 150) & (values < int(self.max_depth * 1000.0))]
        if values.size < 6:
            return None
        z = float(np.median(values)) / 1000.0
        u = 0.5 * (u1 + u2)
        v = 0.5 * (v1 + v2)
        fx = float(info.k[0]) * sx
        fy = float(info.k[4]) * sy
        cx = float(info.k[2]) * sx
        cy = float(info.k[5]) * sy
        if fx <= 0.0 or fy <= 0.0:
            return None
        return ((u - cx) * z / fx, (v - cy) * z / fy, z)

    @staticmethod
    def _rotate_point(point, quaternion):
        x, y, z = point
        qx, qy, qz, qw = quaternion
        tx = 2.0 * (qy * z - qz * y)
        ty = 2.0 * (qz * x - qx * z)
        tz = 2.0 * (qx * y - qy * x)
        return (
            x + qw * tx + (qy * tz - qz * ty),
            y + qw * ty + (qz * tx - qx * tz),
            z + qw * tz + (qx * ty - qy * tx),
        )

    def _to_map(self, point, source_frame: str) -> Optional[Tuple[float, float, float]]:
        try:
            transform = self.tf_buffer.lookup_transform(
                self.map_frame, source_frame, rclpy.time.Time(), timeout=RclpyDuration(seconds=0.15)
            )
        except TransformException:
            return None
        translation = transform.transform.translation
        rotation = transform.transform.rotation
        rotated = self._rotate_point(
            point, (rotation.x, rotation.y, rotation.z, rotation.w)
        )
        return (
            rotated[0] + translation.x,
            rotated[1] + translation.y,
            rotated[2] + translation.z,
        )

    def _update_candidate(self, detection: Detection, stamp: float) -> bool:
        position = detection.position
        if position is None:
            return False

        # Require observations to be temporally continuous. Old, intermittent
        # false positives must not accumulate until they become confirmed.
        self.candidates = [
            candidate
            for candidate in self.candidates
            if candidate.last_seen <= 0.0
            or stamp - candidate.last_seen <= self.candidate_max_gap
        ]
        nearest = None
        nearest_distance = self.merge_distance
        for candidate in self.candidates:
            if candidate.class_name != detection.class_name or not candidate.positions:
                continue
            mean = candidate.mean_position
            distance = math.hypot(mean[0] - position[0], mean[1] - position[1])
            if distance < nearest_distance:
                nearest, nearest_distance = candidate, distance
        if nearest is None:
            nearest = Candidate(detection.class_name, detection.display_name)
            self.candidates.append(nearest)
        nearest.add(position, detection.confidence, stamp)
        is_structural = detection.class_name in self.structural_confidence_thresholds
        required_observations = (
            self.structural_confirm_observations
            if is_structural
            else self.confirm_observations
        )
        required_span = (
            self.structural_confirm_min_span if is_structural else self.confirm_min_span
        )
        if len(nearest.positions) < required_observations:
            return False
        if nearest.last_seen - nearest.first_seen < required_span:
            return False
        if is_structural:
            positions = np.asarray(nearest.positions, dtype=np.float64)
            xy_stddev = float(np.max(np.std(positions[:, :2], axis=0)))
            if xy_stddev > self.structural_max_position_stddev:
                return False
        return self._confirm(nearest)

    def _confirm(self, candidate: Candidate) -> bool:
        x, y, z = candidate.mean_position
        for item in self.confirmed:
            if item.get("class_name") != candidate.class_name:
                continue
            if math.hypot(float(item.get("x", 0.0)) - x, float(item.get("y", 0.0)) - y) < self.merge_distance:
                old_n = int(item.get("observations", 1))
                new_n = len(candidate.positions)
                item["x"] = (float(item["x"]) * old_n + x * new_n) / (old_n + new_n)
                item["y"] = (float(item["y"]) * old_n + y * new_n) / (old_n + new_n)
                item["z"] = (float(item.get("z", 0.0)) * old_n + z * new_n) / (old_n + new_n)
                item["confidence"] = max(float(item.get("confidence", 0.0)), float(np.mean(candidate.confidences)))
                item["observations"] = old_n + new_n
                item["last_seen"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
                self.candidates.remove(candidate)
                return True
        index = 1 + sum(1 for item in self.confirmed if item.get("class_name") == candidate.class_name)
        now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        self.confirmed.append(
            {
                "id": f"auto_{candidate.class_name.replace(' ', '_')}_{index:03d}",
                "class_name": candidate.class_name,
                "display_name": candidate.display_name,
                "floor_id": self.floor_id,
                "frame_id": self.map_frame,
                "x": x,
                "y": y,
                "z": z,
                "confidence": float(np.mean(candidate.confidences)),
                "observations": len(candidate.positions),
                "first_seen": now,
                "last_seen": now,
                "source": "rgbd_multi_frame",
            }
        )
        self.candidates.remove(candidate)
        return True

    def _infer_rooms(self) -> List[Dict]:
        rooms = []
        classes = {str(item.get("class_name")) for item in self.confirmed}
        for room_type, (evidence, display_name) in ROOM_RULES.items():
            matched = evidence & classes
            required = 2 if room_type in {"kitchen", "dining_room"} else 1
            if len(matched) < required:
                continue
            objects = [item for item in self.confirmed if item.get("class_name") in matched]
            rooms.append(
                {
                    "id": f"auto_room_{room_type}_001",
                    "room_type": room_type,
                    "display_name": display_name,
                    "floor_id": self.floor_id,
                    "x": float(np.mean([float(item["x"]) for item in objects])),
                    "y": float(np.mean([float(item["y"]) for item in objects])),
                    "confidence": float(np.mean([float(item.get("confidence", 0.0)) for item in objects])),
                    "evidence": sorted(matched),
                    "status": "candidate",
                }
            )
        return rooms

    @staticmethod
    def _atomic_yaml(path: Path, payload: Dict):
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                yaml.safe_dump(payload, stream, allow_unicode=True, sort_keys=False)
            os.replace(temp_name, path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    @staticmethod
    def _atomic_json(path: Path, payload: Dict):
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            os.replace(temp_name, path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def _map_corners(self) -> List[List[float]]:
        map_msg = self.map_msg
        if map_msg is None:
            return []
        origin = map_msg.info.origin.position
        yaw = _map_origin_yaw(map_msg)
        cos_yaw = math.cos(yaw)
        sin_yaw = math.sin(yaw)
        width = float(map_msg.info.width) * float(map_msg.info.resolution)
        height = float(map_msg.info.height) * float(map_msg.info.resolution)
        corners = []
        for local_x, local_y in ((0.0, 0.0), (width, 0.0), (width, height), (0.0, height), (0.0, 0.0)):
            corners.append(
                [
                    float(origin.x) + cos_yaw * local_x - sin_yaw * local_y,
                    float(origin.y) + sin_yaw * local_x + cos_yaw * local_y,
                ]
            )
        return corners

    def _ensure_semantic_floor_files(self) -> Tuple[Path, str]:
        floor_dir = self.semantic_config_root / self.floor_id
        floor_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = floor_dir / "map_manifest.yaml"
        map_version = f"{self.floor_id}-v1"
        if manifest_path.is_file():
            try:
                with manifest_path.open("r", encoding="utf-8") as stream:
                    manifest = yaml.safe_load(stream) or {}
                map_version = str(manifest.get("map_version", map_version))
            except Exception as exc:
                self.get_logger().warning(f"Cannot read semantic manifest: {exc}")
        else:
            manifest = {
                "site_id": "home",
                "floor_id": self.floor_id,
                "map_id": f"ddsm_map_{self.floor_id}",
                "map_version": map_version,
                "frame_id": self.map_frame,
                "semantic_areas": "semantic_areas.geojson",
                "poi_database": "pois.yaml",
            }
            self._atomic_yaml(manifest_path, manifest)

        areas_path = floor_dir / "semantic_areas.geojson"
        if not areas_path.exists():
            corners = self._map_corners()
            if corners:
                area = {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "properties": {
                                "id": f"{self.floor_id}_unassigned",
                                "display_name": self.floor_id,
                                "area_type": "general",
                                "floor_id": self.floor_id,
                                "priority": 0,
                            },
                            "geometry": {"type": "Polygon", "coordinates": [corners]},
                        }
                    ],
                }
                self._atomic_json(areas_path, area)
        return floor_dir, map_version

    def _write_navigation_artifacts(self):
        if not self.generate_object_waypoints or self.map_msg is None:
            return
        floor_dir, map_version = self._ensure_semantic_floor_files()
        pois_path = floor_dir / "pois.yaml"
        existing = []
        if pois_path.is_file():
            try:
                with pois_path.open("r", encoding="utf-8") as stream:
                    existing = list((yaml.safe_load(stream) or {}).get("pois", []))
            except Exception as exc:
                self.get_logger().warning(f"Cannot read existing POIs: {exc}")

        generated_by = "ddsm_car_control/semantic_mapping_recorder"
        manual = [item for item in existing if item.get("generated_by") != generated_by]
        manual_names = {str(item.get("display_name", "")) for item in manual}
        generated = []
        class_counts: Dict[str, int] = {}
        for item in self.confirmed:
            class_name = str(item.get("class_name", ""))
            if class_name in self.waypoint_excluded_classes:
                item["waypoint_status"] = "excluded"
                item.pop("approach_waypoint", None)
                continue
            class_counts[class_name] = class_counts.get(class_name, 0) + 1
            suffix = class_counts[class_name]
            base_name = str(item.get("display_name", class_name))
            display_name = base_name if suffix == 1 else f"{base_name}{suffix}"
            pose = find_safe_approach_pose(
                self.map_msg,
                float(item["x"]),
                float(item["y"]),
                target_distance=self.approach_distance,
                min_distance=self.approach_min_distance,
                max_distance=self.approach_max_distance,
                required_clearance=self.waypoint_clearance,
            )
            if pose is None:
                item["waypoint_status"] = "no_safe_pose"
                item.pop("approach_waypoint", None)
                continue
            x, y, yaw, clearance = pose
            waypoint = {
                "id": str(item["id"]),
                "display_name": display_name,
                "poi_type": "waypoint",
                "floor_id": self.floor_id,
                "area_id": f"{self.floor_id}_unassigned",
                "x": float(x),
                "y": float(y),
                "yaw": float(yaw),
                "final_approach_profile": "none",
                "enabled": True,
                "map_version": map_version,
                "generated_by": generated_by,
                "source_object_id": str(item["id"]),
                "source_object_class": class_name,
                "source_object_x": float(item["x"]),
                "source_object_y": float(item["y"]),
                "source_confidence": float(item.get("confidence", 0.0)),
                "clearance": float(clearance),
            }
            item["waypoint_status"] = "ready"
            item["approach_waypoint"] = {
                "x": float(x),
                "y": float(y),
                "yaw": float(yaw),
                "clearance": float(clearance),
            }
            if display_name not in manual_names:
                generated.append(waypoint)

        self._atomic_yaml(pois_path, {"pois": manual + generated})
        self.get_logger().info(
            f"Object waypoints updated: generated={len(generated)} manual={len(manual)} file={pois_path}"
        )

    def _save(self):
        try:
            self._write_navigation_artifacts()
            self.last_waypoint_write = time.monotonic()
        except Exception as exc:
            self.get_logger().error(f"Cannot update object waypoints: {exc}")
        payload = {
            "schema_version": "1.0",
            "generated_by": "ddsm_car_control/semantic_mapping_recorder",
            "floor_id": self.floor_id,
            "frame_id": self.map_frame,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "objects": self.confirmed,
            "rooms": self._infer_rooms(),
            "note": "Confirmed objects generate safe approach POIs. Manual POIs are preserved.",
        }
        self._atomic_yaml(self.output_file, payload)

    def _publish_annotated(self, image: np.ndarray, source: Image, detections: List[Detection]):
        if not self.publish_annotated_image or self.image_pub.get_subscription_count() == 0:
            return
        for detection in detections:
            x1, y1, x2, y2 = detection.box
            color = (0, 200, 255) if detection.class_name in {"door", "doorway"} else (0, 255, 80)
            cv2.rectangle(image, (x1, y1), (x2, y2), color, 2)
            label = f"{detection.class_name} {detection.confidence:.2f}"
            cv2.putText(image, label, (x1, max(18, y1 - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
        image = np.ascontiguousarray(image)
        message = Image()
        message.header = source.header
        message.height, message.width = image.shape[:2]
        message.encoding = "bgr8"
        message.is_bigendian = 0
        message.step = message.width * 3
        message.data = image.tobytes()
        self.image_pub.publish(message)

    def _publish_preview(self):
        if not self.publish_annotated_image or self.image_pub.get_subscription_count() == 0:
            return
        with self.lock:
            color_msg = self.color_msg
            detection_age = time.monotonic() - self.preview_detection_time
            detections = list(self.preview_detections)
        if color_msg is None:
            return
        stamp = color_msg.header.stamp.sec + color_msg.header.stamp.nanosec / 1e9
        if not -0.2 <= self.get_clock().now().nanoseconds / 1e9 - stamp <= 1.0:
            return  # Never refresh an old frame as if it were live video.
        if detection_age > self.preview_detection_hold:
            detections = []
        try:
            image = self._color_array(color_msg)
        except Exception as exc:
            self.get_logger().warning(f"Cannot decode preview frame: {exc}")
            return
        self._publish_annotated(image, color_msg, detections)

    def _publish_markers(self):
        message = MarkerArray()
        now = self.get_clock().now().to_msg()
        clear = Marker()
        clear.header.frame_id = self.map_frame
        clear.header.stamp = now
        clear.action = Marker.DELETEALL
        message.markers.append(clear)
        for index, item in enumerate(self.confirmed):
            marker = Marker()
            marker.header.frame_id = self.map_frame
            marker.header.stamp = now
            marker.ns = "semantic_auto_objects"
            marker.id = index
            marker.type = Marker.SPHERE
            marker.action = Marker.ADD
            marker.pose.position.x = float(item["x"])
            marker.pose.position.y = float(item["y"])
            marker.pose.position.z = 0.25
            marker.pose.orientation.w = 1.0
            marker.scale.x = marker.scale.y = marker.scale.z = 0.22
            marker.color.r, marker.color.g, marker.color.b, marker.color.a = 0.1, 0.85, 0.25, 0.9
            marker.lifetime = Duration(sec=0, nanosec=0)
            message.markers.append(marker)
            text_marker = Marker()
            text_marker.header = marker.header
            text_marker.ns = "semantic_auto_labels"
            text_marker.id = index + 10000
            text_marker.type = Marker.TEXT_VIEW_FACING
            text_marker.action = Marker.ADD
            text_marker.pose.position.x = marker.pose.position.x
            text_marker.pose.position.y = marker.pose.position.y
            text_marker.pose.position.z = 0.48
            text_marker.pose.orientation.w = 1.0
            text_marker.scale.z = 0.20
            text_marker.color.r, text_marker.color.g, text_marker.color.b, text_marker.color.a = 1.0, 0.35, 0.1, 1.0
            text_marker.text = str(item.get("display_name", item.get("class_name", "object")))
            message.markers.append(text_marker)
            approach = item.get("approach_waypoint")
            if approach:
                waypoint_marker = Marker()
                waypoint_marker.header = marker.header
                waypoint_marker.ns = "semantic_auto_waypoints"
                waypoint_marker.id = index + 20000
                waypoint_marker.type = Marker.ARROW
                waypoint_marker.action = Marker.ADD
                waypoint_marker.pose.position.x = float(approach["x"])
                waypoint_marker.pose.position.y = float(approach["y"])
                waypoint_marker.pose.position.z = 0.06
                yaw = float(approach["yaw"])
                waypoint_marker.pose.orientation.z = math.sin(yaw * 0.5)
                waypoint_marker.pose.orientation.w = math.cos(yaw * 0.5)
                waypoint_marker.scale.x = 0.42
                waypoint_marker.scale.y = 0.10
                waypoint_marker.scale.z = 0.10
                waypoint_marker.color.r = 0.2
                waypoint_marker.color.g = 0.45
                waypoint_marker.color.b = 1.0
                waypoint_marker.color.a = 0.95
                message.markers.append(waypoint_marker)
        self.marker_pub.publish(message)

    def destroy_node(self):
        self._disable_image_subscriptions()
        if self.furniture_backend == "rknn" and self.furniture_session is not None:
            self.furniture_session.release()
            self.furniture_session = None
        return super().destroy_node()

    def _set_status(self, status: str):
        self.last_status = status
        message = String()
        message.data = status
        self.status_pub.publish(message)

    def _process(self):
        if not self.inference_guard.acquire(blocking=False):
            return
        try:
            self._process_once()
        except Exception as exc:
            self._set_status(f"inference_error: {type(exc).__name__}: {str(exc)[:160]}")
            self.get_logger().error(f"Semantic inference failed: {exc}")
        finally:
            self.inference_guard.release()

    def _process_once(self):
        with self.lock:
            color_msg = self.color_msg
            depth_msg = self.depth_msg
            info_msg = self.info_msg
        if color_msg is None or depth_msg is None or info_msg is None:
            self._set_status("waiting_for_rgbd")
            return
        pair = tuple(m.header.stamp.sec + m.header.stamp.nanosec / 1e9 for m in (color_msg, depth_msg))
        now = self.get_clock().now().nanoseconds / 1e9
        if not all(-0.2 <= now-stamp <= 1.0 for stamp in pair):
            self._set_status(f"waiting_for_fresh_rgbd color_age={now-pair[0]:.2f} depth_age={now-pair[1]:.2f}")
            return
        if abs(pair[0]-pair[1]) > 0.25:
            self._set_status("waiting_for_synchronized_rgbd")
            return
        if self.last_processed_pair is not None and any(
                stamp <= old for stamp, old in zip(pair, self.last_processed_pair)):
            self._set_status("waiting_for_new_rgbd")
            return
        self.last_processed_pair = pair
        started = time.monotonic()
        try:
            image = self._color_array(color_msg)
            depth = self._depth_array(depth_msg)
        except Exception as exc:
            self._set_status(f"image_decode_error: {exc}")
            return
        detections = self._detect_furniture(image) + self._detect_doors(image)
        confirmed_changed = False
        located = 0
        for detection in detections:
            point = self._position_from_depth(detection, depth, info_msg)
            if point is None:
                continue
            detection.position = self._to_map(point, depth_msg.header.frame_id)
            if detection.position is None:
                continue
            located += 1
            confirmed_changed |= self._update_candidate(detection, time.time())
        with self.lock:
            self.preview_detections = list(detections)
            self.preview_detection_time = time.monotonic()
        self._publish_annotated(image.copy(), color_msg, detections)
        if confirmed_changed:
            self._save()
            self._publish_markers()
        self.inference_count += 1
        self._set_status(
            f"running detections={len(detections)} located={located} confirmed={len(self.confirmed)} floor={self.floor_id} "
            f"sequence={self.inference_count} inference_ms={(time.monotonic()-started)*1000:.0f}"
        )


def main(args=None):
    rclpy.init(args=args)
    node = SemanticMappingRecorder()
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    try:
        executor.spin()
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        executor.shutdown()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
