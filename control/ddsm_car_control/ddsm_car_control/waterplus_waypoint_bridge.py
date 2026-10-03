#!/usr/bin/env python3
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Union

import rclpy
from geometry_msgs.msg import Pose, PoseStamped, Quaternion
from nav_msgs.msg import Path as NavPath
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from std_msgs.msg import Empty as EmptyMsg, String
from visualization_msgs.msg import MarkerArray

from ddsm_car_control.ddsm_patrol_manager import (
    PatrolRoute,
    Waypoint,
    dump_route,
    load_route,
    make_route_markers,
    make_route_path,
    normalize_angle,
)

try:
    from waterplus_map_tools.msg import Waypoint as WaterplusWaypoint
    from waterplus_map_tools.srv import (
        AddNewWaypoint,
        GetNumOfWaypoints,
        GetWaypointByIndex,
        GetWaypointByName,
        SaveWaypoints,
    )
except ImportError:  # The pure helper tests run before the interface package is built.
    WaterplusWaypoint = None
    AddNewWaypoint = None
    GetNumOfWaypoints = None
    GetWaypointByIndex = None
    GetWaypointByName = None
    SaveWaypoints = None


PathLike = Union[str, Path]


@dataclass
class WaterplusWaypointRecord:
    name: str
    frame_id: str
    pose: Pose


def yaw_from_quaternion(quat: Quaternion) -> float:
    return math.atan2(
        2.0 * (quat.w * quat.z + quat.x * quat.y),
        1.0 - 2.0 * (quat.y * quat.y + quat.z * quat.z),
    )


def copy_pose(pose: Pose) -> Pose:
    copied = Pose()
    copied.position.x = float(pose.position.x)
    copied.position.y = float(pose.position.y)
    copied.position.z = float(pose.position.z)
    copied.orientation.x = float(pose.orientation.x)
    copied.orientation.y = float(pose.orientation.y)
    copied.orientation.z = float(pose.orientation.z)
    copied.orientation.w = float(pose.orientation.w)
    if copied.orientation.w == 0.0 and copied.orientation.z == 0.0:
        copied.orientation.w = 1.0
    return copied


def next_waypoint_name(records: List[WaterplusWaypointRecord]) -> str:
    highest = 0
    for record in records:
        match = re.fullmatch(r"wp_(\d+)", record.name)
        if match:
            highest = max(highest, int(match.group(1)))
    return f"wp_{highest + 1:03d}"


def unique_waypoint_name(
    requested_name: str,
    records: List[WaterplusWaypointRecord],
) -> str:
    requested_name = requested_name.strip()
    if not requested_name:
        return next_waypoint_name(records)
    existing = {record.name for record in records}
    if requested_name not in existing:
        return requested_name
    suffix = 2
    while f"{requested_name}_{suffix}" in existing:
        suffix += 1
    return f"{requested_name}_{suffix}"


def make_record_from_pose_stamped(
    pose: PoseStamped,
    *,
    existing: List[WaterplusWaypointRecord],
    default_frame_id: str,
    requested_name: str = "",
) -> WaterplusWaypointRecord:
    frame_id = pose.header.frame_id or default_frame_id
    return WaterplusWaypointRecord(
        name=unique_waypoint_name(requested_name, existing),
        frame_id=frame_id,
        pose=copy_pose(pose.pose),
    )


def make_record_from_waterplus_message(
    msg,
    *,
    existing: List[WaterplusWaypointRecord],
    default_frame_id: str,
) -> WaterplusWaypointRecord:
    frame_id = getattr(msg, "frame_id", "") or default_frame_id
    return WaterplusWaypointRecord(
        name=unique_waypoint_name(getattr(msg, "name", ""), existing),
        frame_id=frame_id,
        pose=copy_pose(msg.pose),
    )


def make_record_from_service_request(
    request,
    *,
    existing: List[WaterplusWaypointRecord],
    default_frame_id: str,
) -> WaterplusWaypointRecord:
    return WaterplusWaypointRecord(
        name=unique_waypoint_name(getattr(request, "name", ""), existing),
        frame_id=default_frame_id,
        pose=copy_pose(request.pose),
    )


def make_patrol_route(
    records: List[WaterplusWaypointRecord],
    *,
    route_id: str,
    loop: bool,
    default_dwell_sec: float,
    default_waypoint_type: str,
    default_final_approach: bool,
) -> PatrolRoute:
    waypoints = []
    for record in records:
        waypoints.append(
            Waypoint(
                id=record.name,
                name=record.name,
                x=float(record.pose.position.x),
                y=float(record.pose.position.y),
                yaw=normalize_angle(yaw_from_quaternion(record.pose.orientation)),
                waypoint_type=default_waypoint_type,
                dwell_sec=float(default_dwell_sec),
                final_approach=bool(default_final_approach),
            )
        )
    return PatrolRoute(route_id=route_id, loop=loop, waypoints=waypoints)


def make_records_from_patrol_route(
    route: PatrolRoute,
    *,
    frame_id: str,
) -> List[WaterplusWaypointRecord]:
    records = []
    for waypoint in route.waypoints:
        pose = Pose()
        pose.position.x = float(waypoint.x)
        pose.position.y = float(waypoint.y)
        pose.position.z = 0.0
        half = float(waypoint.yaw) * 0.5
        pose.orientation.z = math.sin(half)
        pose.orientation.w = math.cos(half)
        records.append(
            WaterplusWaypointRecord(
                name=waypoint.name or waypoint.id,
                frame_id=frame_id,
                pose=pose,
            )
        )
    return records


def find_waypoint_by_name(
    records: List[WaterplusWaypointRecord],
    query: str,
) -> Optional[WaterplusWaypointRecord]:
    query = query.strip()
    for record in records:
        if record.name == query:
            return record
    if not query:
        return None
    for record in records:
        if query in record.name:
            return record
    return None


def _append_text(parent: ET.Element, tag: str, value: float | str) -> None:
    child = ET.SubElement(parent, tag)
    child.text = str(value)


def dump_waterplus_xml(path: PathLike, records: List[WaterplusWaypointRecord]) -> None:
    xml_path = Path(path).expanduser()
    xml_path.parent.mkdir(parents=True, exist_ok=True)
    root = ET.Element("Waterplus")
    for record in records:
        waypoint = ET.SubElement(root, "Waypoint")
        _append_text(waypoint, "Name", record.name)
        _append_text(waypoint, "Pos_x", float(record.pose.position.x))
        _append_text(waypoint, "Pos_y", float(record.pose.position.y))
        _append_text(waypoint, "Pos_z", float(record.pose.position.z))
        _append_text(waypoint, "Ori_x", float(record.pose.orientation.x))
        _append_text(waypoint, "Ori_y", float(record.pose.orientation.y))
        _append_text(waypoint, "Ori_z", float(record.pose.orientation.z))
        _append_text(waypoint, "Ori_w", float(record.pose.orientation.w))
    ET.ElementTree(root).write(xml_path, encoding="utf-8", xml_declaration=True)


class WaterplusWaypointBridge(Node):
    def __init__(self) -> None:
        super().__init__("ddsm_waterplus_bridge")
        if WaterplusWaypoint is None:
            raise RuntimeError(
                "waterplus_map_tools interfaces are not available; build and source "
                "the waterplus_map_tools package first"
            )

        self.declare_parameter("route_file", "/home/sunrise/luka_ws/common/config/patrol_route.yaml")
        self.declare_parameter("waterplus_file", "/home/sunrise/luka_ws/common/config/waypoints.xml")
        self.declare_parameter("map_frame", "map")
        self.declare_parameter("route_id", "waterplus_route")
        self.declare_parameter("default_dwell_sec", 0.0)
        self.declare_parameter("default_waypoint_type", "stop")
        self.declare_parameter("default_final_approach", False)
        self.declare_parameter("enable_goal_pose_alias", True)
        self.declare_parameter("goal_pose_topic", "/goal_pose")

        self.route_file = Path(str(self.get_parameter("route_file").value)).expanduser()
        self.waterplus_file = Path(str(self.get_parameter("waterplus_file").value)).expanduser()
        self.map_frame = str(self.get_parameter("map_frame").value)
        self.route_id = str(self.get_parameter("route_id").value)
        self.default_dwell_sec = float(self.get_parameter("default_dwell_sec").value)
        self.default_waypoint_type = str(self.get_parameter("default_waypoint_type").value)
        self.default_final_approach = bool(
            self.get_parameter("default_final_approach").value
        )
        self.enable_goal_pose_alias = bool(
            self.get_parameter("enable_goal_pose_alias").value
        )
        self.goal_pose_topic = str(self.get_parameter("goal_pose_topic").value).strip()
        if not self.goal_pose_topic:
            self.goal_pose_topic = "/goal_pose"

        self.records: List[WaterplusWaypointRecord] = []
        self.pending_start_timer = None
        self.pending_start_publisher = None
        self.pending_start_status = ""
        self.load_existing_route()

        self.status_pub = self.create_publisher(String, "/waterplus/status", 10)
        self.path_pub = self.create_publisher(NavPath, "/waterplus/waypoint_path", 1)
        self.markers_pub = self.create_publisher(
            MarkerArray,
            "/waterplus/waypoint_markers",
            1,
        )
        self.patrol_load_pub = self.create_publisher(String, "/patrol/load_route", 10)
        self.patrol_start_once_pub = self.create_publisher(EmptyMsg, "/patrol/start_once", 10)
        self.patrol_start_loop_pub = self.create_publisher(EmptyMsg, "/patrol/start_loop", 10)
        self.patrol_stop_pub = self.create_publisher(EmptyMsg, "/patrol/stop", 10)

        self.create_subscription(
            WaterplusWaypoint,
            "/waterplus/add_waypoint",
            self.on_add_waterplus_waypoint,
            10,
        )
        self.create_subscription(
            PoseStamped,
            "/waterplus/add_waypoint_pose",
            self.on_add_pose_stamped,
            10,
        )
        if self.enable_goal_pose_alias:
            self.create_subscription(
                PoseStamped,
                self.goal_pose_topic,
                self.on_add_goal_pose_alias,
                10,
            )
        self.create_subscription(EmptyMsg, "/waterplus/clear_waypoints", self.on_clear, 10)
        self.create_subscription(EmptyMsg, "/waterplus/save", self.on_save, 10)
        self.create_subscription(EmptyMsg, "/waterplus/start_once", self.on_start_once, 10)
        self.create_subscription(EmptyMsg, "/waterplus/start_loop", self.on_start_loop, 10)
        self.create_subscription(EmptyMsg, "/waterplus/stop", self.on_stop, 10)

        self.create_service(AddNewWaypoint, "/waterplus/add_new_waypoint", self.on_add_service)
        self.create_service(
            GetNumOfWaypoints,
            "/waterplus/get_num_waypoint",
            self.on_get_num_waypoint,
        )
        self.create_service(
            GetWaypointByIndex,
            "/waterplus/get_waypoint_index",
            self.on_get_waypoint_index,
        )
        self.create_service(
            GetWaypointByName,
            "/waterplus/get_waypoint_name",
            self.on_get_waypoint_name,
        )
        self.create_service(SaveWaypoints, "/waterplus/save_waypoints", self.on_save_service)

        self.create_timer(1.0, self.publish_visuals)
        self.persist()
        self.publish_status(f"ready:{len(self.records)}")
        if self.enable_goal_pose_alias:
            self.get_logger().info(
                f"Foxglove goal pose alias enabled: {self.goal_pose_topic} -> "
                "/waterplus/add_waypoint_pose"
            )

    def load_existing_route(self) -> None:
        if not self.route_file.exists():
            return
        try:
            self.records = make_records_from_patrol_route(
                load_route(self.route_file),
                frame_id=self.map_frame,
            )
        except (OSError, ValueError) as exc:
            self.get_logger().warn(f"cannot load patrol route {self.route_file}: {exc}")

    def publish_status(self, status: str) -> None:
        msg = String()
        msg.data = status
        self.status_pub.publish(msg)
        self.get_logger().info(f"waterplus status: {status}")

    def make_route(self, *, loop: bool = False) -> PatrolRoute:
        return make_patrol_route(
            self.records,
            route_id=self.route_id,
            loop=loop,
            default_dwell_sec=self.default_dwell_sec,
            default_waypoint_type=self.default_waypoint_type,
            default_final_approach=self.default_final_approach,
        )

    def persist(self) -> None:
        dump_route(self.route_file, self.make_route(loop=False))
        dump_waterplus_xml(self.waterplus_file, self.records)
        load_msg = String()
        load_msg.data = str(self.route_file)
        self.patrol_load_pub.publish(load_msg)
        self.publish_visuals()

    def schedule_patrol_start(self, publisher, status: str) -> None:
        if self.pending_start_timer is not None:
            self.pending_start_timer.cancel()
            self.destroy_timer(self.pending_start_timer)
        self.pending_start_publisher = publisher
        self.pending_start_status = status
        self.pending_start_timer = self.create_timer(0.25, self.publish_pending_start)

    def publish_pending_start(self) -> None:
        timer = self.pending_start_timer
        self.pending_start_timer = None
        if timer is not None:
            timer.cancel()
            self.destroy_timer(timer)
        if self.pending_start_publisher is None:
            return
        self.pending_start_publisher.publish(EmptyMsg())
        self.publish_status(self.pending_start_status)
        self.pending_start_publisher = None
        self.pending_start_status = ""

    def add_record(self, record: WaterplusWaypointRecord) -> bool:
        if record.frame_id != self.map_frame:
            self.publish_status(f"frame_mismatch:{record.frame_id}")
            return False
        self.records.append(record)
        self.persist()
        self.publish_status(f"added:{record.name}")
        return True

    def publish_visuals(self) -> None:
        route = self.make_route(loop=False)
        path = make_route_path(route, self.map_frame)
        path.header.stamp = self.get_clock().now().to_msg()
        for pose in path.poses:
            pose.header.stamp = path.header.stamp
        self.path_pub.publish(path)

        markers = make_route_markers(route, self.map_frame)
        stamp = self.get_clock().now().to_msg()
        for marker in markers.markers:
            marker.header.stamp = stamp
        self.markers_pub.publish(markers)

    def on_add_waterplus_waypoint(self, msg) -> None:
        self.add_record(
            make_record_from_waterplus_message(
                msg,
                existing=self.records,
                default_frame_id=self.map_frame,
            )
        )

    def on_add_pose_stamped(self, msg: PoseStamped) -> None:
        self.add_record(
            make_record_from_pose_stamped(
                msg,
                existing=self.records,
                default_frame_id=self.map_frame,
            )
        )

    def on_add_goal_pose_alias(self, msg: PoseStamped) -> None:
        self.add_record(
            make_record_from_pose_stamped(
                msg,
                existing=self.records,
                default_frame_id=self.map_frame,
            )
        )

    def on_add_service(self, request, response):
        response.result = self.add_record(
            make_record_from_service_request(
                request,
                existing=self.records,
                default_frame_id=self.map_frame,
            )
        )
        return response

    def on_clear(self, _msg: EmptyMsg) -> None:
        self.records.clear()
        self.persist()
        self.publish_status("cleared")

    def on_save(self, _msg: EmptyMsg) -> None:
        self.persist()
        self.publish_status(f"saved:{self.waterplus_file}")

    def on_start_once(self, _msg: EmptyMsg) -> None:
        if not self.records:
            self.publish_status("route_empty")
            self.get_logger().warn("start_once ignored: waypoint route is empty")
            return
        self.persist()
        self.schedule_patrol_start(self.patrol_start_once_pub, "start_once")

    def on_start_loop(self, _msg: EmptyMsg) -> None:
        if not self.records:
            self.publish_status("route_empty")
            self.get_logger().warn("start_loop ignored: waypoint route is empty")
            return
        dump_route(self.route_file, self.make_route(loop=True))
        dump_waterplus_xml(self.waterplus_file, self.records)
        load_msg = String()
        load_msg.data = str(self.route_file)
        self.patrol_load_pub.publish(load_msg)
        self.schedule_patrol_start(self.patrol_start_loop_pub, "start_loop")

    def on_stop(self, _msg: EmptyMsg) -> None:
        self.patrol_stop_pub.publish(EmptyMsg())
        self.publish_status("stopped")

    def on_get_num_waypoint(self, _request, response):
        response.num = len(self.records)
        return response

    def on_get_waypoint_index(self, request, response):
        if 0 <= request.index < len(self.records):
            record = self.records[request.index]
            response.name = record.name
            response.pose = copy_pose(record.pose)
        return response

    def on_get_waypoint_name(self, request, response):
        record = find_waypoint_by_name(self.records, request.name)
        if record is not None:
            response.name = record.name
            response.pose = copy_pose(record.pose)
        return response

    def on_save_service(self, request, response):
        filename = request.filename.strip()
        if filename:
            dump_waterplus_xml(filename, self.records)
        else:
            dump_waterplus_xml(self.waterplus_file, self.records)
        dump_route(self.route_file, self.make_route(loop=False))
        self.publish_status(f"saved:{filename or self.waterplus_file}")
        return response


def main(args=None) -> None:
    rclpy.init(args=args)
    node = WaterplusWaypointBridge()
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
