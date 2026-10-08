"""ROS-native selected-target gate for D-Robotics person following.

This node performs no inference. It consumes the canonical Luka person
observation topics, applies fail-closed selection/geometry/TF checks, and feeds
only one selected person to the official tros_person_following node.
"""
from __future__ import annotations

import copy
import json
import math
import time

import rclpy
from ai_msgs.msg import Attribute, PerceptionTargets, Roi, Target
from geometry_msgs.msg import PointStamped
from rclpy.node import Node
from rclpy.time import Time
from std_msgs.msg import Int64, String
from std_srvs.srv import SetBool
from tf2_geometry_msgs import do_transform_point
from tf2_ros import Buffer, TransformListener

from .target_gate import selected_target
from .tracking_mode import normalize_tracking_mode, selection_policy


def _attrs(target):
    return {item.type: float(item.value) for item in target.attributes}


def _message_rows(msg):
    rows = []
    for target in msg.targets:
        if target.type and target.type != "person":
            continue
        roi = next((item for item in target.rois if item.type in ("body", "person")), None)
        if roi is None and target.rois:
            roi = target.rois[0]
        if roi is None:
            continue
        attrs = _attrs(target)
        bbox = [
            int(roi.rect.x_offset),
            int(roi.rect.y_offset),
            int(roi.rect.x_offset + roi.rect.width),
            int(roi.rect.y_offset + roi.rect.height),
        ]
        rows.append({
            "class": "person",
            "track_id": int(target.track_id),
            "bbox": bbox,
            "confidence": float(roi.confidence),
            "depth_valid": attrs.get("depth_valid", 0.0) > 0.5,
            "seg_depth_trimmed_mean": attrs.get("seg_depth_trimmed_mean", 0.0) > 0.5,
            "observation_strength": (
                "strong" if attrs.get("observation_strong", 0.0) > 0.5 else "weak"
            ),
            "association_ambiguous": attrs.get("association_ambiguous", 0.0) > 0.5,
            "visible": attrs.get("visible", 1.0) > 0.5,
            "position_optical_m": [
                attrs.get("optical_x_m"),
                attrs.get("optical_y_m"),
                attrs.get("optical_z_m"),
            ],
            "width_m": attrs.get("width_m"),
            "height_m": attrs.get("height_m"),
        })
    return rows


class SelectedBridge(Node):
    def __init__(self):
        super().__init__("selected_bridge")
        # Kept as a no-op compatibility parameter so old launch invocations do
        # not break. No HTTP request is made anywhere in this node.
        self.declare_parameter(
            "status_url", "http://127.0.0.1:8098/api/people/follow-state")
        self.input_topic = str(self.declare_parameter(
            "perception_topic", "/luka/perception/person_targets").value)
        self.selection_topic = str(self.declare_parameter(
            "selection_topic", "/luka/perception/selected_track_id").value)
        self.output_topic = str(self.declare_parameter(
            "output_topic", "/luka/follow/selected_target").value)
        self.legacy_output_topic = str(self.declare_parameter(
            "legacy_output_topic", "/luka/selected_seg_targets").value)
        self.tracking_mode = normalize_tracking_mode(self.declare_parameter(
            "tracking_mode", "selected").value)
        self.auto_select_first_person = bool(self.declare_parameter(
            "auto_select_first_person", False).value)
        self.depth_invalid_grace_sec = float(self.declare_parameter(
            "depth_invalid_grace_sec", .25).value)
        self.max_depth_jump_m = float(self.declare_parameter(
            "max_depth_jump_m", .6).value)

        self.pub = self.create_publisher(PerceptionTargets, self.output_topic, 10)
        self.legacy_pub = (
            self.create_publisher(PerceptionTargets, self.legacy_output_topic, 10)
            if self.legacy_output_topic and self.legacy_output_topic != self.output_topic
            else None
        )
        self.diag = self.create_publisher(
            String, "/luka_person_following/adapter_status", 10)

        self.tf = Buffer()
        self.listener = TransformListener(self.tf, self)
        self.create_subscription(
            PerceptionTargets, self.input_topic, self.on_perception, 10)
        self.create_subscription(
            Int64, self.selection_topic, self.on_selection, 10)

        self.client = self.create_client(
            SetBool, "/luka_person_following/official/enable_follow")
        self.create_service(
            SetBool, "/luka_person_following/set_enabled", self.set_enabled)

        from luka_motion_gateway.client import MotionLeaseClient
        from luka_behaviors.follow_navigation import FollowNavigationProxy
        self.motion=MotionLeaseClient(self)
        self.base_gate=self.create_client(SetBool,'/nx/navigation_enable')
        self.motion_future=None;self.base_future=None;self.base_enabled=False;self.motion_armed=False
        self.follow_navigation=FollowNavigationProxy(self,self.motion,lambda:self.desired and self.valid and self.robot_tf_ready and self.base_enabled)
        self.latest_msg = None
        self.latest_rows = []
        self.latest_received_mono = None
        self.selected_track_id = None

        self.desired = False
        self.applied = None
        self.pending = None
        self.last_id = None
        self.valid = False
        self.robot_tf_ready = False
        self.reason = "starting"
        self.current_block_reason = None
        self.last_disarm_reason = None
        self.last_disarm_time = None
        self.last_valid_row = None
        self.last_valid_track_id = None
        self.last_valid_mono = None

        self.create_timer(.125, self.poll)

    def on_perception(self, msg):
        self.latest_msg = msg
        self.latest_rows = _message_rows(msg)
        self.latest_received_mono = time.monotonic()

    def on_selection(self, msg):
        if self.tracking_mode == "automatic":
            self.selected_track_id = None
            return
        self.selected_track_id = None if int(msg.data) < 0 else int(msg.data)

    def set_enabled(self, request, response):
        if request.data and (
            not self.valid
            or not self.robot_tf_ready
            or not self.client.service_is_ready()
        ):
            response.success = False
            response.message = "Cannot enable: " + (
                self.reason if not self.valid
                else "map/base/camera TF or controller unavailable"
            )
        else:
            if request.data and (not self.base_gate.service_is_ready() or not self.motion.status):
                response.success=False;response.message='Base or motion gateway unavailable';return response
            self.motion_armed=False
            self.desired = bool(request.data)
            self.base_future=self.base_gate.call_async(SetBool.Request(data=bool(request.data)))
            if not request.data:self.motion.stop()
            self.current_block_reason = None if request.data else "manual_disable"
            response.success = True
            response.message = (
                "Enable requested" if request.data else "Disable requested")
        return response

    def sync_enable(self):
        lease_valid=self.motion.valid('follow') or self.motion.valid('nav')
        if self.motion_armed and not lease_valid:self.desired=False
        if lease_valid:self.motion_armed=True
        if self.base_future is not None and self.base_future.done():
            try:self.base_enabled=self.base_future.result().success and self.desired
            except Exception:self.base_enabled=False
            self.base_future=None
            if not self.base_enabled:self.desired=False
        if self.motion_future is not None and self.motion_future.done():
            try:self.motion_future.result()
            except Exception:self.desired=False
            self.motion_future=None
        if self.desired and self.base_enabled and self.motion.desired is None and self.motion_future is None:
            self.motion_future=self.motion.request('follow')
        if not self.desired:
            self.motion.release()
            if self.base_enabled and self.base_gate.service_is_ready():
                self.base_gate.call_async(SetBool.Request(data=False));self.base_enabled=False
        if self.pending is not None:
            if not self.pending.done():
                return
            try:
                response = self.pending.result()
                self.applied = self.pending_value if response.success else None
            except Exception:
                self.applied = None
            self.pending = None
        permitted=self.desired and self.base_enabled and (self.motion.valid('follow') or self.motion.valid('nav'))
        if self.applied != permitted and self.client.service_is_ready():
            req = SetBool.Request()
            req.data = permitted
            self.pending_value = permitted
            self.pending = self.client.call_async(req)

    def _message_age(self):
        if self.latest_msg is None or self.latest_received_mono is None:
            return math.inf
        age = max(0.0, time.monotonic() - self.latest_received_mono)
        stamp = self.latest_msg.header.stamp
        stamp_s = float(stamp.sec) + float(stamp.nanosec) / 1e9
        if stamp_s > 0:
            now_s = self.get_clock().now().nanoseconds / 1e9
            header_age = now_s - stamp_s
            # Only use comparable system/ROS clock values. A negative or huge
            # delta may indicate simulated time or a clock-domain mismatch.
            if 0.0 <= header_age <= 3600.0:
                age = max(age, header_age)
        return age

    @staticmethod
    def _empty_message(now_msg):
        msg = PerceptionTargets()
        msg.header.stamp = now_msg
        msg.header.frame_id = "camera_link"
        return msg

    def _publish_output(self, msg):
        self.pub.publish(msg)
        if self.legacy_pub is not None:
            self.legacy_pub.publish(msg)

    def poll(self):
        msg = self._empty_message(self.get_clock().now().to_msg())
        row = None
        effective_id = self.selected_track_id
        held = False
        try:
            age = self._message_age()
            requested_id, auto_select = selection_policy(
                self.tracking_mode,
                self.selected_track_id,
                self.auto_select_first_person,
            )
            row, self.reason, effective_id = selected_target(
                self.latest_rows,
                requested_id,
                age,
                auto_select_first_person=auto_select,
            )

            if (
                row is None
                and self.reason in (
                    "invalid_seg_depth",
                    "invalid_seg_depth_method",
                    "depth_jump_rejected",
                )
                and self.last_valid_row is not None
                and effective_id == self.last_valid_track_id
                and self.last_valid_mono is not None
                and time.monotonic() - self.last_valid_mono <= self.depth_invalid_grace_sec
            ):
                row = copy.deepcopy(self.last_valid_row)
                self.reason = "selected_seg_depth_held"
                held = True

            if row is not None and not held and self.last_valid_row is not None:
                old_z = self.last_valid_row["position_optical_m"][2]
                new_z = row["position_optical_m"][2]
                if abs(float(new_z) - float(old_z)) > self.max_depth_jump_m:
                    row = None
                    self.reason = "depth_jump_rejected"
                    if (
                        effective_id == self.last_valid_track_id
                        and self.last_valid_mono is not None
                        and time.monotonic() - self.last_valid_mono
                        <= self.depth_invalid_grace_sec
                    ):
                        row = copy.deepcopy(self.last_valid_row)
                        self.reason = "selected_seg_depth_held"
                        held = True

            if row is not None:
                if self.latest_msg is None or not self.latest_msg.header.frame_id:
                    raise ValueError("missing optical frame")
                point = PointStamped()
                point.header = self.latest_msg.header
                point.point.x, point.point.y, point.point.z = map(
                    float, row["position_optical_m"])
                transform = self.tf.lookup_transform(
                    "camera_link", point.header.frame_id, Time())
                p = do_transform_point(point, transform).point
                if not (.1 <= p.x <= 4.0 and -3.0 <= p.y <= 3.0):
                    raise ValueError("selected point outside official following range")

                if not held:
                    self.last_valid_row = copy.deepcopy(row)
                    self.last_valid_track_id = int(row["track_id"])
                    self.last_valid_mono = time.monotonic()

                target = Target()
                target.type = "person"
                target.track_id = int(row["track_id"])
                roi = Roi()
                roi.type = "person"
                roi.confidence = float(row["confidence"])
                x1, y1, x2, y2 = map(int, row["bbox"])
                roi.rect.x_offset = max(0, x1)
                roi.rect.y_offset = max(0, y1)
                roi.rect.width = max(0, x2 - x1)
                roi.rect.height = max(0, y2 - y1)
                target.rois = [roi]
                for key, value in (
                    ("x_cm", p.x * 100.0),
                    ("y_cm", p.y * 100.0),
                    ("width_cm", row["width_m"] * 100.0),
                    ("height_cm", row["height_m"] * 100.0),
                ):
                    attr = Attribute()
                    attr.type = key
                    attr.value = float(value)
                    attr.confidence = roi.confidence
                    target.attributes.append(attr)
                msg.header.stamp = self.latest_msg.header.stamp
                msg.targets = [target]
        except Exception as exc:
            row = None
            self.reason = "source_or_tf_unavailable: " + str(exc)[:160]

        self.valid = row is not None and bool(msg.targets)
        self.robot_tf_ready = (
            self.tf.can_transform("map", "base_footprint", Time())
            and self.tf.can_transform("map", "camera_link", Time())
        )
        current_id = int(row["track_id"]) if self.valid else None

        disarm_reason = None
        if not self.valid:
            disarm_reason = self.reason
        elif not self.robot_tf_ready:
            disarm_reason = "tf_unavailable"
        elif self.last_id is not None and current_id != self.last_id:
            # A trajectory ID change is never treated as identity continuity.
            disarm_reason = "track_id_changed"

        if disarm_reason is not None:
            self.desired = False
            self.current_block_reason = disarm_reason
            if disarm_reason != self.last_disarm_reason:
                self.last_disarm_reason = disarm_reason
                self.last_disarm_time = time.time()
        elif self.desired:
            self.current_block_reason = None

        self.last_id = current_id
        self.sync_enable()

        # Finish controller cancellation before presenting changed/empty input.
        if (self.desired and self.base_enabled and (self.motion.valid('follow') or self.motion.valid('nav'))) or self.applied is not True:
            self._publish_output(msg)

        status = {
            "valid": self.valid,
            "reason": self.reason,
            "source": "ros2",
            "tracking_mode": self.tracking_mode,
            "input_topic": self.input_topic,
            "selected_track_id": current_id,
            "requested_track_id": self.selected_track_id,
            "enabled_requested": self.desired,
            "enabled_applied": self.applied,
            "robot_tf_ready": self.robot_tf_ready,
            "depth_method": "seg_valid_trimmed_mean",
            "optical_frame": (
                self.latest_msg.header.frame_id if self.latest_msg is not None else None
            ),
            "source_age_s": None if self.latest_received_mono is None else self._message_age(),
            "current_block_reason": self.current_block_reason,
            "last_disarm_reason": self.last_disarm_reason,
            "last_disarm_time": self.last_disarm_time,
            "depth_hold": self.reason == "selected_seg_depth_held",
        }
        self.diag.publish(String(data=json.dumps(status, ensure_ascii=False)))


def main():
    rclpy.init()
    node = SelectedBridge()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()
