#!/usr/bin/env python3
"""Navigate to versioned, named hotel destinations."""

from __future__ import annotations

import json
import math
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import rclpy
from action_msgs.msg import GoalStatus
from ament_index_python.packages import get_package_share_directory
from geometry_msgs.msg import PoseStamped, PoseWithCovarianceStamped
from nav2_msgs.action import NavigateToPose
from rclpy.action import ActionClient, ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import ExternalShutdownException, MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import Bool, Empty as EmptyMsg, String
from std_srvs.srv import Empty as EmptySrv

from hotel_semantic_map_msgs.action import NavigateToNamedDestination

from .models import Poi
from .store import (
    SemanticMapData,
    find_area,
    load_semantic_map,
    parse_floor_context,
    resolve_destination,
)


class TerminalAlignmentDeadline:
    """Once near the destination, bound the remaining alignment attempt."""
    def __init__(self, timeout):
        self.timeout = timeout
        self.started = None

    def expired(self, now, distance, pose_fresh):
        if self.started is None and pose_fresh and 0.0 <= distance <= 0.20:
            self.started = now
        return self.started is not None and now - self.started >= self.timeout


class NavGoalResponseGuard:
    """Cancel a late accepted goal even after its caller has stopped waiting."""
    def __init__(self):
        self.lock = threading.Lock()
        self.handle = None
        self.abandoned = False
        self.cancel_sent = False

    def _cancel_candidate(self):
        if self.abandoned and self.handle is not None and self.handle.accepted and not self.cancel_sent:
            self.cancel_sent = True
            return self.handle
        return None

    def received(self, handle):
        with self.lock:
            self.handle = handle
            cancel = self._cancel_candidate()
        if cancel is not None:
            cancel.cancel_goal_async()

    def abandon(self):
        with self.lock:
            self.abandoned = True
            cancel = self._cancel_candidate()
        if cancel is not None:
            cancel.cancel_goal_async()


@dataclass(frozen=True)
class TopicCommand:
    destination_id: str
    use_final_approach: Optional[bool] = None
    map_version: str = ""


def parse_topic_command(value: str) -> TopicCommand:
    text = value.strip()
    if not text:
        raise ValueError("destination command is empty")
    if not text.startswith("{"):
        return TopicCommand(destination_id=text)
    document = json.loads(text)
    if not isinstance(document, dict):
        raise ValueError("destination command JSON must be an object")
    destination_id = str(
        document.get("destination_id") or document.get("data") or ""
    ).strip()
    if not destination_id:
        raise ValueError("destination_id is required")
    requested_final = document.get("use_final_approach")
    if requested_final is not None and not isinstance(requested_final, bool):
        raise ValueError("use_final_approach must be true or false")
    return TopicCommand(
        destination_id=destination_id,
        use_final_approach=requested_final,
        map_version=str(document.get("map_version", "")).strip(),
    )


def infer_final_approach(poi: Poi) -> bool:
    return poi.final_approach_profile.strip().casefold() not in {"", "none", "disabled"}


def covariance_is_ready(
    covariance,
    *,
    xy_std_threshold: float,
    yaw_std_threshold: float,
) -> bool:
    if len(covariance) < 36:
        return False
    variances = (float(covariance[0]), float(covariance[7]), float(covariance[35]))
    if any(not math.isfinite(value) or value < 0.0 for value in variances):
        return False
    return (
        math.sqrt(variances[0]) <= xy_std_threshold
        and math.sqrt(variances[1]) <= xy_std_threshold
        and math.sqrt(variances[2]) <= yaw_std_threshold
    )


def classify_final_status(status: str) -> str:
    normalized = status.strip().casefold()
    if normalized == "final_reached":
        return "success"
    failure_tokens = (
        "blocked_front",
        "cancelled",
        "failed",
        "goal_rejected",
        "missing_final_goal",
        "nav_server_unavailable",
        "rejected_goal_frame",
        "timeout",
    )
    if any(token in normalized for token in failure_tokens):
        return "failure"
    return "pending"


def _default_manifest() -> str:
    return str(
        Path(get_package_share_directory("hotel_semantic_map"))
        / "config"
        / "map_manifest.yaml"
    )


def _pose_from_poi(poi: Poi, frame_id: str, stamp) -> PoseStamped:
    pose = PoseStamped()
    pose.header.frame_id = frame_id
    pose.header.stamp = stamp
    pose.pose.position.x = poi.x
    pose.pose.position.y = poi.y
    pose.pose.position.z = 0.0
    pose.pose.orientation.z = math.sin(poi.yaw * 0.5)
    pose.pose.orientation.w = math.cos(poi.yaw * 0.5)
    return pose


class NamedNavigationServer(Node):
    def __init__(self) -> None:
        super().__init__("hotel_named_navigation_server")
        self.declare_parameter("manifest_file", _default_manifest())
        self.declare_parameter("action_name", "/hotel/navigate_to_destination")
        self.declare_parameter("navigate_action", "navigate_to_pose")
        self.declare_parameter("final_goal_topic", "/final_approach/goal_pose")
        self.declare_parameter("final_status_topic", "/final_approach/status")
        self.declare_parameter("final_cancel_service", "/final_approach/cancel")
        self.declare_parameter("patrol_stop_topic", "/patrol/stop")
        self.declare_parameter("localization_ready_topic", "/localization/ready")
        self.declare_parameter("amcl_pose_topic", "/amcl_pose")
        self.declare_parameter("goal_topic", "/hotel/goal_destination")
        self.declare_parameter("cancel_topic", "/hotel/cancel")
        self.declare_parameter("status_topic", "/hotel/navigation_status")
        self.declare_parameter("require_localization_ready", True)
        self.declare_parameter("localization_wait_timeout", 60.0)
        self.declare_parameter("localization_max_age", 5.0)
        self.declare_parameter("localization_stable_samples", 3)
        self.declare_parameter("localization_xy_std_threshold", 0.25)
        self.declare_parameter("localization_yaw_std_threshold", 0.30)
        self.declare_parameter("nav_server_timeout", 5.0)
        self.declare_parameter("navigation_timeout", 300.0)
        self.declare_parameter("terminal_alignment_timeout", 15.0)
        self.declare_parameter("final_approach_timeout", 90.0)
        self.declare_parameter("cancel_patrol_on_goal", True)
        self.declare_parameter("floor_context_topic", "/hotel/floor_context")

        self.manifest_file = Path(
            str(self.get_parameter("manifest_file").value)
        ).expanduser()
        self.action_name = str(self.get_parameter("action_name").value)
        self.require_localization_ready = bool(
            self.get_parameter("require_localization_ready").value
        )
        self.localization_wait_timeout = float(
            self.get_parameter("localization_wait_timeout").value
        )
        self.localization_max_age = float(
            self.get_parameter("localization_max_age").value
        )
        self.localization_stable_samples = int(
            self.get_parameter("localization_stable_samples").value
        )
        self.localization_xy_std_threshold = float(
            self.get_parameter("localization_xy_std_threshold").value
        )
        self.localization_yaw_std_threshold = float(
            self.get_parameter("localization_yaw_std_threshold").value
        )
        self.nav_server_timeout = float(self.get_parameter("nav_server_timeout").value)
        self.navigation_timeout = float(self.get_parameter("navigation_timeout").value)
        self.terminal_alignment_timeout = max(1.0, float(self.get_parameter("terminal_alignment_timeout").value))
        self.terminal_pause_client = self.create_client(EmptySrv, "/base_control/pause_now")
        self.final_approach_timeout = float(
            self.get_parameter("final_approach_timeout").value
        )
        self.cancel_patrol_on_goal = bool(
            self.get_parameter("cancel_patrol_on_goal").value
        )

        self.callback_group = ReentrantCallbackGroup()
        self.nav_client = ActionClient(
            self,
            NavigateToPose,
            str(self.get_parameter("navigate_action").value),
            callback_group=self.callback_group,
        )
        self.final_goal_pub = self.create_publisher(
            PoseStamped, str(self.get_parameter("final_goal_topic").value), 10
        )
        self.patrol_stop_pub = self.create_publisher(
            EmptyMsg, str(self.get_parameter("patrol_stop_topic").value), 10
        )
        self.status_pub = self.create_publisher(
            String, str(self.get_parameter("status_topic").value), 10
        )
        context_qos = QoSProfile(depth=1)
        context_qos.reliability = ReliabilityPolicy.RELIABLE
        context_qos.durability = DurabilityPolicy.TRANSIENT_LOCAL
        self.create_subscription(
            String,
            str(self.get_parameter("floor_context_topic").value),
            self._on_floor_context,
            context_qos,
            callback_group=self.callback_group,
        )
        self.final_cancel_client = self.create_client(
            EmptySrv,
            str(self.get_parameter("final_cancel_service").value),
            callback_group=self.callback_group,
        )

        self.create_subscription(
            Bool,
            str(self.get_parameter("localization_ready_topic").value),
            self._on_localization_ready,
            10,
            callback_group=self.callback_group,
        )
        self.create_subscription(
            PoseWithCovarianceStamped,
            str(self.get_parameter("amcl_pose_topic").value),
            self._on_amcl_pose,
            10,
            callback_group=self.callback_group,
        )
        self.create_subscription(
            String,
            str(self.get_parameter("final_status_topic").value),
            self._on_final_status,
            10,
            callback_group=self.callback_group,
        )
        self.create_subscription(
            String,
            str(self.get_parameter("goal_topic").value),
            self._on_topic_goal,
            10,
            callback_group=self.callback_group,
        )
        self.create_subscription(
            EmptyMsg,
            str(self.get_parameter("cancel_topic").value),
            self._on_topic_cancel,
            10,
            callback_group=self.callback_group,
        )

        self._goal_lock = threading.Lock()
        self._goal_reserved = False
        self._active_server_goal = None
        self._external_cancel = threading.Event()
        self._nav_goal_handle = None
        self._topic_goal_handle = None
        self._topic_goal_pending = False
        self._external_localization_ready = False
        self._amcl_ready = False
        self._amcl_stable_count = 0
        self._last_amcl_monotonic = 0.0
        self._last_amcl_xy: Optional[tuple[float, float]] = None
        self._final_status_queue: queue.Queue[str] = queue.Queue()
        self._final_mission_active = False
        self._last_final_status = ""
        self._last_final_status_monotonic = 0.0

        self.action_server = ActionServer(
            self,
            NavigateToNamedDestination,
            self.action_name,
            execute_callback=self._execute,
            goal_callback=self._goal_callback,
            cancel_callback=self._cancel_callback,
            callback_group=self.callback_group,
        )
        self.topic_action_client = ActionClient(
            self,
            NavigateToNamedDestination,
            self.action_name,
            callback_group=self.callback_group,
        )
        self._publish_status("ready")
        self.get_logger().info(
            "Named navigation ready | "
            f"action={self.action_name} manifest={self.manifest_file}"
        )

    def _publish_status(self, state: str, **fields) -> None:
        payload = {"state": state, **{key: value for key, value in fields.items() if value}}
        message = String()
        message.data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        self.status_pub.publish(message)
        self.get_logger().info(message.data)

    def _on_floor_context(self, message: String) -> None:
        try:
            context = parse_floor_context(message.data)
            manifest = Path(context.semantic_manifest_file).expanduser().resolve()
            data = load_semantic_map(manifest)
            if data.identity.floor_id != context.floor_id:
                raise ValueError(
                    f"manifest floor {data.identity.floor_id!r} does not match "
                    f"requested floor {context.floor_id!r}"
                )
        except Exception as error:
            self._publish_status("floor_context_rejected", message=str(error))
            return
        with self._goal_lock:
            if self._goal_reserved:
                self._publish_status(
                    "floor_context_rejected_busy", floor_id=context.floor_id
                )
                return
            self.manifest_file = manifest
        self._publish_status(
            "floor_context_ready",
            floor_id=context.floor_id,
            map_version=data.identity.map_version,
        )

    def _on_localization_ready(self, message: Bool) -> None:
        self._external_localization_ready = bool(message.data)

    def _on_amcl_pose(self, message: PoseWithCovarianceStamped) -> None:
        if message.header.frame_id and message.header.frame_id != "map":
            return
        self._last_amcl_xy = (
            float(message.pose.pose.position.x),
            float(message.pose.pose.position.y),
        )
        self._last_amcl_monotonic = time.monotonic()
        ready = covariance_is_ready(
            message.pose.covariance,
            xy_std_threshold=self.localization_xy_std_threshold,
            yaw_std_threshold=self.localization_yaw_std_threshold,
        )
        self._amcl_stable_count = self._amcl_stable_count + 1 if ready else 0
        self._amcl_ready = self._amcl_stable_count >= self.localization_stable_samples

    def _on_final_status(self, message: String) -> None:
        self._last_final_status = message.data
        self._last_final_status_monotonic = time.monotonic()
        if self._final_mission_active:
            self._final_status_queue.put(message.data)

    def _localization_is_ready(self) -> bool:
        if not self.require_localization_ready:
            return True
        amcl_fresh = (
            self._amcl_ready
            and self._last_amcl_monotonic > 0.0
            and time.monotonic() - self._last_amcl_monotonic <= self.localization_max_age
        )
        return self._external_localization_ready or amcl_fresh

    def _current_area(self, data: SemanticMapData) -> str:
        if self._last_amcl_xy is None:
            return ""
        area = find_area(data.areas, self._last_amcl_xy[0], self._last_amcl_xy[1])
        return area.id if area is not None else ""

    def _goal_callback(self, _request) -> GoalResponse:
        with self._goal_lock:
            if self._goal_reserved:
                self._publish_status("rejected_busy")
                return GoalResponse.REJECT
            self._goal_reserved = True
        return GoalResponse.ACCEPT

    def _cancel_callback(self, _goal_handle) -> CancelResponse:
        self._external_cancel.set()
        return CancelResponse.ACCEPT

    def _feedback(
        self,
        goal_handle,
        data: SemanticMapData,
        phase: str,
        distance_remaining: float = -1.0,
    ) -> None:
        feedback = NavigateToNamedDestination.Feedback()
        feedback.phase = phase
        feedback.current_area_id = self._current_area(data)
        feedback.distance_remaining = float(distance_remaining)
        goal_handle.publish_feedback(feedback)

    def _make_result(
        self,
        *,
        success: bool,
        destination_id: str = "",
        failure_code: str = "",
        message: str = "",
    ):
        result = NavigateToNamedDestination.Result()
        result.success = success
        result.resolved_destination_id = destination_id
        result.failure_code = failure_code
        result.message = message
        return result

    def _abort(self, goal_handle, destination_id: str, code: str, message: str):
        goal_handle.abort()
        self._publish_status(
            "failed",
            destination_id=destination_id,
            failure_code=code,
            message=message,
        )
        return self._make_result(
            success=False,
            destination_id=destination_id,
            failure_code=code,
            message=message,
        )

    def _cancelled(self, goal_handle, destination_id: str):
        if goal_handle.is_cancel_requested:
            goal_handle.canceled()
        else:
            goal_handle.abort()
        self._publish_status("cancelled", destination_id=destination_id)
        return self._make_result(
            success=False,
            destination_id=destination_id,
            failure_code="CANCELLED",
            message="navigation was cancelled",
        )

    def _is_cancel_requested(self, goal_handle) -> bool:
        return goal_handle.is_cancel_requested or self._external_cancel.is_set()

    def _cancel_active_motion(self) -> None:
        if self._nav_goal_handle is not None:
            self._nav_goal_handle.cancel_goal_async()
            self._nav_goal_handle = None
        if self.final_cancel_client.service_is_ready():
            self.final_cancel_client.call_async(EmptySrv.Request())

    def _wait_for_localization(self, goal_handle, data: SemanticMapData) -> bool:
        deadline = time.monotonic() + self.localization_wait_timeout
        while not self._localization_is_ready():
            if self._is_cancel_requested(goal_handle):
                return False
            if time.monotonic() >= deadline:
                return False
            self._feedback(goal_handle, data, "waiting_localization")
            time.sleep(0.1)
        return True

    def _execute(self, goal_handle):
        request = goal_handle.request
        requested_id = request.destination_id.strip()
        resolved_id = requested_id
        self._active_server_goal = goal_handle
        self._external_cancel.clear()
        try:
            if not requested_id:
                return self._abort(
                    goal_handle, "", "INVALID_REQUEST", "destination_id is required"
                )
            try:
                data = load_semantic_map(self.manifest_file)
            except Exception as error:
                return self._abort(
                    goal_handle, requested_id, "SEMANTIC_MAP_NOT_READY", str(error)
                )
            if request.map_version and request.map_version != data.identity.map_version:
                return self._abort(
                    goal_handle,
                    requested_id,
                    "MAP_VERSION_MISMATCH",
                    f"requested {request.map_version}, active {data.identity.map_version}",
                )
            resolved = resolve_destination(data.pois, requested_id, data.identity.floor_id)
            if resolved is None:
                return self._abort(
                    goal_handle,
                    requested_id,
                    "DESTINATION_NOT_FOUND",
                    f"destination '{requested_id}' was not found",
                )
            poi = resolved.poi
            resolved_id = poi.id
            self._publish_status(
                "accepted",
                destination_id=resolved_id,
                request_id=request.request_id,
            )
            if not self._wait_for_localization(goal_handle, data):
                if self._is_cancel_requested(goal_handle):
                    return self._cancelled(goal_handle, resolved_id)
                return self._abort(
                    goal_handle,
                    resolved_id,
                    "LOCALIZATION_TIMEOUT",
                    "localization did not become ready before timeout",
                )
            if self.cancel_patrol_on_goal:
                patrol_stop_time = time.monotonic()
                self.patrol_stop_pub.publish(EmptyMsg())
                deadline = patrol_stop_time + 0.5
                while time.monotonic() < deadline:
                    if (
                        self._last_final_status_monotonic >= patrol_stop_time
                        and self._last_final_status == "cancelled"
                    ):
                        break
                    time.sleep(0.05)
            if self._is_cancel_requested(goal_handle):
                return self._cancelled(goal_handle, resolved_id)
            if request.use_final_approach:
                return self._run_final_approach(goal_handle, data, poi)
            return self._run_nav2(goal_handle, data, poi)
        except Exception as error:
            self.get_logger().error(f"Unhandled named-navigation error: {error}")
            return self._abort(goal_handle, resolved_id, "INTERNAL_ERROR", str(error))
        finally:
            self._final_mission_active = False
            self._active_server_goal = None
            self._nav_goal_handle = None
            self._external_cancel.clear()
            with self._goal_lock:
                self._goal_reserved = False

    def _run_nav2(self, goal_handle, data: SemanticMapData, poi: Poi):
        if not self.nav_client.wait_for_server(timeout_sec=self.nav_server_timeout):
            return self._abort(
                goal_handle,
                poi.id,
                "NAV_SERVER_UNAVAILABLE",
                "NavigateToPose action server is unavailable",
            )
        goal = NavigateToPose.Goal()
        goal.pose = _pose_from_poi(poi, data.identity.frame_id, self.get_clock().now().to_msg())
        response_event = threading.Event()
        result_event = threading.Event()
        state = {"goal_handle": None, "response_error": None, "result": None}
        latest_distance = {"value": -1.0}
        response_guard = NavGoalResponseGuard()

        def on_feedback(message) -> None:
            latest_distance["value"] = float(message.feedback.distance_remaining)
            self._feedback(
                goal_handle, data, "navigating", latest_distance["value"]
            )

        def on_response(future) -> None:
            try:
                state["goal_handle"] = future.result()
                response_guard.received(state["goal_handle"])
            except Exception as error:
                state["response_error"] = error
            response_event.set()

        self._publish_status("preparing", destination_id=poi.id)
        send_future = self.nav_client.send_goal_async(goal, feedback_callback=on_feedback)
        send_future.add_done_callback(on_response)
        response_deadline = time.monotonic() + self.nav_server_timeout
        while not response_event.wait(0.1):
            if self._is_cancel_requested(goal_handle):
                response_guard.abandon()
                return self._cancelled(goal_handle, poi.id)
            if time.monotonic() >= response_deadline:
                response_guard.abandon()
                return self._abort(
                    goal_handle, poi.id, "NAV_GOAL_TIMEOUT", "Nav2 did not accept the goal"
                )
        if state["response_error"] is not None:
            return self._abort(
                goal_handle,
                poi.id,
                "NAV_GOAL_ERROR",
                str(state["response_error"]),
            )
        nav_goal_handle = state["goal_handle"]
        if nav_goal_handle is None or not nav_goal_handle.accepted:
            return self._abort(
                goal_handle, poi.id, "NAV_GOAL_REJECTED", "Nav2 rejected the goal"
            )
        self._nav_goal_handle = nav_goal_handle
        if self._is_cancel_requested(goal_handle):
            response_guard.abandon()
            return self._cancelled(goal_handle, poi.id)
        # Only announce navigation after Nav2 acknowledges the goal.
        self._publish_status("navigating", destination_id=poi.id)

        def on_result(future) -> None:
            try:
                state["result"] = future.result()
            except Exception as error:
                state["response_error"] = error
            result_event.set()

        nav_goal_handle.get_result_async().add_done_callback(on_result)
        deadline = time.monotonic() + self.navigation_timeout
        alignment_deadline = TerminalAlignmentDeadline(self.terminal_alignment_timeout)
        while not result_event.wait(0.1):
            if self._is_cancel_requested(goal_handle):
                nav_goal_handle.cancel_goal_async()
                return self._cancelled(goal_handle, poi.id)
            if time.monotonic() >= deadline:
                nav_goal_handle.cancel_goal_async()
                return self._abort(
                    goal_handle,
                    poi.id,
                    "NAVIGATION_TIMEOUT",
                    "navigation exceeded its timeout",
                )
            distance = self._estimated_distance(poi)
            if alignment_deadline.expired(time.monotonic(), distance,
                    time.monotonic() - self._last_amcl_monotonic <= self.localization_max_age):
                nav_goal_handle.cancel_goal_async()
                if self.terminal_pause_client.service_is_ready():
                    self.terminal_pause_client.call_async(EmptySrv.Request())
                return self._abort(goal_handle, poi.id, "ALIGNMENT_TIMEOUT",
                                   "terminal alignment did not finish; cancellation and parking requested")
            self._feedback(goal_handle, data, "navigating", latest_distance["value"])
        self._nav_goal_handle = None
        if state["response_error"] is not None:
            return self._abort(
                goal_handle,
                poi.id,
                "NAV_RESULT_ERROR",
                str(state["response_error"]),
            )
        nav_result = state["result"]
        if nav_result is None or nav_result.status != GoalStatus.STATUS_SUCCEEDED:
            status = nav_result.status if nav_result is not None else -1
            return self._abort(
                goal_handle,
                poi.id,
                "NAVIGATION_FAILED",
                f"Nav2 finished with status {status}",
            )
        goal_handle.succeed()
        self._publish_status("succeeded", destination_id=poi.id)
        return self._make_result(
            success=True,
            destination_id=poi.id,
            message=f"arrived at {poi.display_name}",
        )

    def _estimated_distance(self, poi: Poi) -> float:
        if self._last_amcl_xy is None:
            return -1.0
        return math.hypot(
            poi.x - self._last_amcl_xy[0], poi.y - self._last_amcl_xy[1]
        )

    def _run_final_approach(self, goal_handle, data: SemanticMapData, poi: Poi):
        while True:
            try:
                self._final_status_queue.get_nowait()
            except queue.Empty:
                break
        self._final_mission_active = True
        self._publish_status(
            "final_approach",
            destination_id=poi.id,
            profile=poi.final_approach_profile,
        )
        self.final_goal_pub.publish(
            _pose_from_poi(poi, data.identity.frame_id, self.get_clock().now().to_msg())
        )
        deadline = time.monotonic() + self.final_approach_timeout
        last_status = "starting"
        while time.monotonic() < deadline:
            if self._is_cancel_requested(goal_handle):
                self._cancel_active_motion()
                return self._cancelled(goal_handle, poi.id)
            try:
                last_status = self._final_status_queue.get(timeout=0.1)
            except queue.Empty:
                pass
            self._feedback(
                goal_handle,
                data,
                f"final_approach:{last_status}",
                self._estimated_distance(poi),
            )
            outcome = classify_final_status(last_status)
            if outcome == "success":
                goal_handle.succeed()
                self._publish_status("succeeded", destination_id=poi.id)
                return self._make_result(
                    success=True,
                    destination_id=poi.id,
                    message=f"final approach completed at {poi.display_name}",
                )
            if outcome == "failure":
                return self._abort(
                    goal_handle,
                    poi.id,
                    "FINAL_APPROACH_FAILED",
                    last_status,
                )
        self._cancel_active_motion()
        return self._abort(
            goal_handle,
            poi.id,
            "FINAL_APPROACH_TIMEOUT",
            "final approach exceeded its timeout",
        )

    def _on_topic_goal(self, message: String) -> None:
        requested_id = ""
        try:
            command = parse_topic_command(message.data)
            requested_id = command.destination_id
            data = load_semantic_map(self.manifest_file)
            resolved = resolve_destination(
                data.pois, command.destination_id, data.identity.floor_id
            )
            if resolved is None:
                raise ValueError(f"destination '{command.destination_id}' was not found")
        except Exception as error:
            self._publish_status("failed", destination_id=requested_id,
                                 failure_code="INVALID_REQUEST", message=str(error))
            return
        if self._topic_goal_pending or self._topic_goal_handle is not None:
            self._publish_status("rejected_busy", destination_id=resolved.poi.id)
            return
        use_final = (
            command.use_final_approach
            if command.use_final_approach is not None
            else infer_final_approach(resolved.poi)
        )
        goal = NavigateToNamedDestination.Goal()
        goal.map_version = command.map_version
        goal.destination_id = resolved.poi.id
        goal.use_final_approach = use_final
        goal.request_id = f"foxglove-{time.time_ns()}"
        self._topic_goal_pending = True
        try:
            future = self.topic_action_client.send_goal_async(goal)
            future.add_done_callback(lambda f: self._on_topic_goal_response(f, resolved.poi.id))
        except Exception as error:
            self._topic_goal_pending = False
            self._publish_status("failed", destination_id=resolved.poi.id,
                                 failure_code="NAMED_GOAL_ERROR", message=str(error))

    def _on_topic_goal_response(self, future, destination_id="") -> None:
        self._topic_goal_pending = False
        try:
            goal_handle = future.result()
        except Exception as error:
            self._publish_status("failed", destination_id=destination_id,
                                 failure_code="NAMED_GOAL_ERROR", message=str(error))
            return
        if not goal_handle.accepted:
            self._publish_status("failed", destination_id=destination_id,
                                 failure_code="NAMED_GOAL_REJECTED", message="Named navigation goal rejected")
            return
        self._topic_goal_handle = goal_handle
        goal_handle.get_result_async().add_done_callback(self._on_topic_result)

    def _on_topic_result(self, future) -> None:
        self._topic_goal_handle = None
        try:
            wrapped = future.result()
            result = wrapped.result
        except Exception as error:
            self._publish_status("topic_result_error", message=str(error))
            return
        self._publish_status(
            "topic_result",
            destination_id=result.resolved_destination_id,
            failure_code=result.failure_code,
            message=result.message,
        )

    def _on_topic_cancel(self, _message: EmptyMsg) -> None:
        self._external_cancel.set()
        if self._topic_goal_handle is not None:
            self._topic_goal_handle.cancel_goal_async()
        self._cancel_active_motion()
        self._publish_status("cancel_requested")


def main(args=None) -> None:
    rclpy.init(args=args)
    node = NamedNavigationServer()
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
