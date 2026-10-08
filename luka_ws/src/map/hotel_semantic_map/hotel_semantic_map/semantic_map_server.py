#!/usr/bin/env python3
"""ROS services and Foxglove markers for a hotel semantic map."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Iterable, Sequence

import rclpy
from ament_index_python.packages import get_package_share_directory
from geometry_msgs.msg import Point
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import String
from std_srvs.srv import Trigger
from visualization_msgs.msg import Marker, MarkerArray

from hotel_semantic_map_msgs.msg import Destination, SemanticMapStatus
from hotel_semantic_map_msgs.srv import GetCurrentArea, ListDestinations, ResolveDestination

from .models import Poi, SemanticArea
from .store import (
    SemanticMapData,
    find_area,
    load_semantic_map,
    parse_floor_context,
    resolve_destination,
)


def _default_manifest() -> str:
    return str(
        Path(get_package_share_directory("hotel_semantic_map"))
        / "config"
        / "map_manifest.yaml"
    )


def _quaternion_from_yaw(yaw: float) -> tuple[float, float]:
    return math.sin(yaw * 0.5), math.cos(yaw * 0.5)


def destination_message(poi: Poi) -> Destination:
    message = Destination()
    message.id = poi.id
    message.display_name = poi.display_name
    message.poi_type = poi.poi_type
    message.floor_id = poi.floor_id
    message.area_id = poi.area_id
    message.pose.position.x = poi.x
    message.pose.position.y = poi.y
    message.pose.position.z = 0.0
    message.pose.orientation.z, message.pose.orientation.w = _quaternion_from_yaw(poi.yaw)
    message.final_approach_profile = poi.final_approach_profile
    message.enabled = poi.enabled
    return message


def _polygons(area: SemanticArea) -> list[Sequence]:
    coordinates = area.geometry.get("coordinates", [])
    if area.geometry.get("type") == "Polygon":
        return [coordinates]
    return list(coordinates)


def _area_color(area_type: str) -> tuple[float, float, float]:
    colors = {
        "corridor": (0.1, 0.8, 0.95),
        "elevator_lobby": (1.0, 0.65, 0.1),
        "guest_room_zone": (0.35, 0.9, 0.35),
        "lobby": (0.75, 0.45, 1.0),
        "restricted": (1.0, 0.2, 0.2),
        "service": (0.95, 0.75, 0.15),
    }
    return colors.get(area_type, (0.2, 0.75, 0.95))


class SemanticMapServer(Node):
    def __init__(self) -> None:
        super().__init__("hotel_semantic_map_server")
        self.declare_parameter("manifest_file", _default_manifest())
        self.declare_parameter("marker_topic", "/semantic_map/markers")
        self.declare_parameter("dynamic_marker_topic", "/semantic_mapping/markers")
        self.declare_parameter("status_topic", "/semantic_map/status")
        self.declare_parameter("republish_period", 5.0)
        self.declare_parameter("floor_context_topic", "/hotel/floor_context")

        qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        self._marker_publisher = self.create_publisher(
            MarkerArray, self.get_parameter("marker_topic").value, qos
        )
        self._dynamic_markers: list[Marker] = []
        self._dynamic_marker_subscription = self.create_subscription(
            MarkerArray,
            self.get_parameter("dynamic_marker_topic").value,
            self._on_dynamic_markers,
            qos,
        )
        self._status_publisher = self.create_publisher(
            SemanticMapStatus, self.get_parameter("status_topic").value, qos
        )
        self._list_service = self.create_service(
            ListDestinations, "/semantic_map/list_destinations", self._list_destinations
        )
        self._resolve_service = self.create_service(
            ResolveDestination,
            "/semantic_map/resolve_destination",
            self._resolve_destination,
        )
        self._area_service = self.create_service(
            GetCurrentArea, "/semantic_map/get_current_area", self._get_current_area
        )
        self._reload_service = self.create_service(
            Trigger, "/semantic_map/reload", self._reload
        )
        self._context_subscription = self.create_subscription(
            String,
            str(self.get_parameter("floor_context_topic").value),
            self._on_floor_context,
            qos,
        )

        self._data: SemanticMapData | None = None
        self._active_manifest_file = self.manifest_file
        self._load()
        period = max(1.0, float(self.get_parameter("republish_period").value))
        self._timer = self.create_timer(period, self._publish_snapshot)

    @property
    def manifest_file(self) -> Path:
        return Path(str(self.get_parameter("manifest_file").value)).expanduser()

    def _load(self, manifest_file: Path | None = None, expected_floor: str = "") -> bool:
        candidate_manifest = manifest_file or self._active_manifest_file
        try:
            candidate = load_semantic_map(candidate_manifest)
            if expected_floor and candidate.identity.floor_id != expected_floor:
                raise ValueError(
                    f"manifest floor {candidate.identity.floor_id!r} does not match "
                    f"requested floor {expected_floor!r}"
                )
        except Exception as error:
            self.get_logger().error(f"Failed to load semantic map: {error}")
            self._publish_status(False, str(error))
            return False
        self._data = candidate
        self._active_manifest_file = candidate_manifest
        self._dynamic_markers = []
        self.get_logger().info(
            "Loaded semantic map "
            f"{self._data.identity.map_id}@{self._data.identity.map_version}: "
            f"{len(self._data.areas)} areas, {len(self._data.pois)} destinations"
        )
        self._publish_status(True, "ready")
        self._publish_snapshot()
        return True

    def _on_floor_context(self, message: String) -> None:
        try:
            context = parse_floor_context(message.data)
            manifest = Path(context.semantic_manifest_file).expanduser().resolve()
        except Exception as error:
            self.get_logger().error(f"Rejected floor context: {error}")
            self._publish_status(False, f"floor context rejected: {error}")
            return
        if self._load(manifest, context.floor_id):
            self.get_logger().info(
                f"Floor context active: {context.floor_id} manifest={manifest}"
            )

    def _publish_status(self, ready: bool, message: str) -> None:
        status = SemanticMapStatus()
        status.header.stamp = self.get_clock().now().to_msg()
        if self._data is not None:
            status.header.frame_id = self._data.identity.frame_id
            status.site_id = self._data.identity.site_id
            status.floor_id = self._data.identity.floor_id
            status.map_version = self._data.identity.map_version
        status.ready = ready
        status.message = message
        self._status_publisher.publish(status)

    def _publish_snapshot(self) -> None:
        if self._data is None:
            return
        static_markers = self._make_markers()
        combined = MarkerArray()
        clear = Marker()
        clear.header.frame_id = self._data.identity.frame_id
        clear.header.stamp = self.get_clock().now().to_msg()
        clear.action = Marker.DELETEALL
        combined.markers.append(clear)
        combined.markers.extend(static_markers.markers)
        combined.markers.extend(self._dynamic_markers)
        self._marker_publisher.publish(combined)

    def _on_dynamic_markers(self, message: MarkerArray) -> None:
        self._dynamic_markers = [
            marker for marker in message.markers if marker.action == Marker.ADD
        ]
        self._publish_snapshot()

    def _make_markers(self) -> MarkerArray:
        assert self._data is not None
        result = MarkerArray()
        now = self.get_clock().now().to_msg()
        frame_id = self._data.identity.frame_id
        marker_id = 0

        for area in self._data.areas:
            all_outer_points = []
            red, green, blue = _area_color(area.area_type)
            for polygon in _polygons(area):
                if not polygon:
                    continue
                outer = polygon[0]
                line = Marker()
                line.header.frame_id = frame_id
                line.header.stamp = now
                line.ns = "semantic_areas"
                line.id = marker_id
                marker_id += 1
                line.type = Marker.LINE_STRIP
                line.action = Marker.ADD
                line.pose.orientation.w = 1.0
                line.scale.x = 0.045
                line.color.r = red
                line.color.g = green
                line.color.b = blue
                line.color.a = 0.95
                for coordinate in outer:
                    point = Point()
                    point.x = float(coordinate[0])
                    point.y = float(coordinate[1])
                    point.z = 0.05
                    line.points.append(point)
                    all_outer_points.append(point)
                result.markers.append(line)

            if all_outer_points:
                label = Marker()
                label.header.frame_id = frame_id
                label.header.stamp = now
                label.ns = "semantic_area_labels"
                label.id = marker_id
                marker_id += 1
                label.type = Marker.TEXT_VIEW_FACING
                label.action = Marker.ADD
                label.pose.position.x = sum(point.x for point in all_outer_points) / len(
                    all_outer_points
                )
                label.pose.position.y = sum(point.y for point in all_outer_points) / len(
                    all_outer_points
                )
                label.pose.position.z = 0.24
                label.pose.orientation.w = 1.0
                label.scale.z = 0.22
                label.color.r = red
                label.color.g = green
                label.color.b = blue
                label.color.a = 1.0
                label.text = area.display_name
                result.markers.append(label)

        for poi in self._data.pois:
            if not poi.enabled:
                continue
            arrow = Marker()
            arrow.header.frame_id = frame_id
            arrow.header.stamp = now
            arrow.ns = "semantic_destinations"
            arrow.id = marker_id
            marker_id += 1
            arrow.type = Marker.ARROW
            arrow.action = Marker.ADD
            arrow.pose = destination_message(poi).pose
            arrow.pose.position.z = 0.08
            arrow.scale.x = 0.28
            arrow.scale.y = 0.08
            arrow.scale.z = 0.08
            arrow.color.r = 1.0
            arrow.color.g = 0.25
            arrow.color.b = 0.65
            arrow.color.a = 1.0
            result.markers.append(arrow)

            label = Marker()
            label.header.frame_id = frame_id
            label.header.stamp = now
            label.ns = "semantic_destination_labels"
            label.id = marker_id
            marker_id += 1
            label.type = Marker.TEXT_VIEW_FACING
            label.action = Marker.ADD
            label.pose.position.x = poi.x
            label.pose.position.y = poi.y
            label.pose.position.z = 0.34
            label.pose.orientation.w = 1.0
            label.scale.z = 0.17
            label.color.r = 1.0
            label.color.g = 0.35
            label.color.b = 0.72
            label.color.a = 1.0
            label.text = poi.display_name
            result.markers.append(label)
        return result

    def _list_destinations(self, request, response):
        if self._data is None:
            return response
        response.destinations = [
            destination_message(poi)
            for poi in self._data.pois
            if (not request.floor_id or poi.floor_id == request.floor_id)
            and (not request.poi_type or poi.poi_type == request.poi_type)
            and (not request.enabled_only or poi.enabled)
        ]
        return response

    def _resolve_destination(self, request, response):
        if self._data is None:
            response.error_code = "NOT_READY"
            response.message = "semantic map is not ready"
            return response
        resolved = resolve_destination(self._data.pois, request.query, request.floor_id)
        if resolved is None:
            response.error_code = "NOT_FOUND"
            response.message = f"destination '{request.query}' was not found"
            return response
        response.success = True
        response.destination = destination_message(resolved.poi)
        response.message = f"matched_by={resolved.matched_by}"
        return response

    def _get_current_area(self, request, response):
        if self._data is None:
            response.error_code = "NOT_READY"
            response.message = "semantic map is not ready"
            return response
        frame_id = request.pose.header.frame_id
        if frame_id and frame_id != self._data.identity.frame_id:
            response.error_code = "FRAME_MISMATCH"
            response.message = (
                f"pose frame '{frame_id}' is not '{self._data.identity.frame_id}'"
            )
            return response
        area = find_area(
            self._data.areas,
            request.pose.pose.position.x,
            request.pose.pose.position.y,
        )
        if area is None:
            response.error_code = "NO_AREA"
            response.message = "pose is outside all named areas"
            return response
        response.success = True
        response.area_id = area.id
        response.display_name = area.display_name
        response.area_type = area.area_type
        response.message = "ok"
        return response

    def _reload(self, _request, response):
        response.success = self._load()
        response.message = "reloaded" if response.success else "reload failed; see node log"
        return response


def main(args=None) -> None:
    rclpy.init(args=args)
    node = SemanticMapServer()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
