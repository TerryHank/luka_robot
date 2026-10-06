"""ROS-native, motion-free publication of Luka person observations."""
from __future__ import annotations

import json
import math
import time

import rclpy
from ai_msgs.msg import Attribute, PerceptionTargets, Roi, Target
from rclpy.node import Node
from std_msgs.msg import Int64, String


def _finite(value):
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if math.isfinite(value) else None


def build_target_specs(snapshot):
    """Build a privacy-minimized, ROS-independent target representation."""
    specs = []
    for row in snapshot.get("tracks") or []:
        try:
            track_id = int(row.get("track_id"))
        except (TypeError, ValueError):
            continue
        bbox = row.get("bbox")
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            continue
        try:
            x1, y1, x2, y2 = [int(v) for v in bbox]
        except (TypeError, ValueError):
            continue
        if x2 <= x1 or y2 <= y1:
            continue
        confidence = _finite(row.get("confidence"))
        confidence = 0.0 if confidence is None else confidence
        attrs = {
            "depth_valid": 1.0 if row.get("depth_valid") is True else 0.0,
            "observation_strong": 1.0 if row.get("observation_strength") == "strong" else 0.0,
            "association_ambiguous": 1.0 if row.get("association_ambiguous") is True else 0.0,
            "visible": 0.0 if row.get("visible") is False else 1.0,
        }
        diagnostic = row.get("depth_diagnostic")
        if isinstance(diagnostic, dict):
            attrs["seg_depth_trimmed_mean"] = (
                1.0 if diagnostic.get("method") == "seg_valid_trimmed_mean" else 0.0
            )
            xyz = diagnostic.get("position_optical_m")
            if isinstance(xyz, (list, tuple)) and len(xyz) == 3:
                for name, value in zip(("optical_x_m", "optical_y_m", "optical_z_m"), xyz):
                    value = _finite(value)
                    if value is not None:
                        attrs[name] = value
            for src, dst in (
                ("width_m", "width_m"),
                ("height_m", "height_m"),
                ("valid_fraction", "depth_valid_fraction"),
                ("rgb_depth_skew_s", "rgb_depth_skew_s"),
            ):
                value = _finite(diagnostic.get(src))
                if value is not None:
                    attrs[dst] = value
        specs.append({
            "track_id": track_id,
            "bbox": [x1, y1, x2, y2],
            "confidence": confidence,
            "attributes": attrs,
        })
    return specs


class RosObservationPublisher:
    """Publisher-only ROS node; it has no motion interfaces."""

    def __init__(self, optical_frame="camera_color_optical_frame"):
        if not rclpy.ok():
            rclpy.init(args=None)
        self.node = Node("luka_person_observation_publisher")
        self.optical_frame = str(optical_frame)
        self.targets_pub = self.node.create_publisher(
            PerceptionTargets, "/luka/perception/person_targets", 10)
        self.selected_pub = self.node.create_publisher(
            Int64, "/luka/perception/selected_track_id", 10)
        self.diag_pub = self.node.create_publisher(
            String, "/luka/perception/person_diagnostics", 10)

    @staticmethod
    def _set_stamp(header, frame_at):
        frame_at = _finite(frame_at)
        if frame_at is None or frame_at < 0:
            return
        sec = int(frame_at)
        nanosec = int(round((frame_at - sec) * 1_000_000_000))
        if nanosec >= 1_000_000_000:
            sec += 1
            nanosec -= 1_000_000_000
        header.stamp.sec = sec
        header.stamp.nanosec = max(0, nanosec)

    def publish(self, snapshot):
        msg = PerceptionTargets()
        msg.header.frame_id = self.optical_frame
        self._set_stamp(msg.header, snapshot.get("frame_at"))
        fps = _finite(snapshot.get("fps"))
        msg.fps = int(round(fps)) if fps is not None and fps >= 0 else -1

        for spec in build_target_specs(snapshot):
            target = Target()
            target.type = "person"
            target.track_id = spec["track_id"]
            roi = Roi()
            roi.type = "body"
            roi.confidence = float(spec["confidence"])
            x1, y1, x2, y2 = spec["bbox"]
            roi.rect.x_offset = max(0, x1)
            roi.rect.y_offset = max(0, y1)
            roi.rect.width = max(0, x2 - x1)
            roi.rect.height = max(0, y2 - y1)
            target.rois = [roi]
            for name, value in spec["attributes"].items():
                attr = Attribute()
                attr.type = name
                attr.value = float(value)
                attr.confidence = float(spec["confidence"])
                target.attributes.append(attr)
            msg.targets.append(target)
        self.targets_pub.publish(msg)

        selected = Int64()
        try:
            selected.data = int(snapshot.get("selected_track_id"))
        except (TypeError, ValueError):
            selected.data = -1
        self.selected_pub.publish(selected)

        frame_mono = _finite(snapshot.get("frame_mono"))
        age = None if frame_mono is None else max(0.0, time.monotonic() - frame_mono)
        diag = {
            "targets": len(msg.targets),
            "selected_track_id": None if selected.data < 0 else selected.data,
            "frame_age_s": age,
            "loading": snapshot.get("loading") is True,
            "error": snapshot.get("error"),
            "metric_depth_available": snapshot.get("metric_depth_available") is True,
            "optical_frame": self.optical_frame,
        }
        self.diag_pub.publish(String(
            data=json.dumps(diag, ensure_ascii=False, allow_nan=False)))
