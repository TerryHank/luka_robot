import math
import xml.etree.ElementTree as ET

from geometry_msgs.msg import Pose, PoseStamped

from ddsm_car_control.waterplus_waypoint_bridge import (
    WaterplusWaypointRecord,
    dump_waterplus_xml,
    find_waypoint_by_name,
    make_patrol_route,
    make_record_from_pose_stamped,
    make_record_from_waterplus_message,
    next_waypoint_name,
    yaw_from_quaternion,
)
from ddsm_car_control.ddsm_patrol_manager import yaw_to_quaternion


def test_next_waypoint_name_skips_existing_numbers():
    records = [
        WaterplusWaypointRecord(name="wp_001", frame_id="map", pose=Pose()),
        WaterplusWaypointRecord(name="wp_003", frame_id="map", pose=Pose()),
        WaterplusWaypointRecord(name="lobby", frame_id="map", pose=Pose()),
    ]

    assert next_waypoint_name(records) == "wp_004"


def test_make_record_from_pose_stamped_uses_map_frame_and_yaw():
    pose = PoseStamped()
    pose.header.frame_id = "map"
    pose.pose.position.x = 1.2
    pose.pose.position.y = -0.4
    pose.pose.orientation = yaw_to_quaternion(math.pi / 2.0)

    record = make_record_from_pose_stamped(
        pose,
        existing=[],
        default_frame_id="map",
    )

    assert record.name == "wp_001"
    assert record.frame_id == "map"
    assert math.isclose(record.pose.position.x, 1.2)
    assert math.isclose(record.pose.position.y, -0.4)
    assert math.isclose(yaw_from_quaternion(record.pose.orientation), math.pi / 2.0)


def test_make_record_from_waterplus_message_preserves_name_and_frame():
    class FakeWaterplusMessage:
        pass

    msg = FakeWaterplusMessage()
    msg.name = "room_801"
    msg.frame_id = ""
    msg.pose = Pose()
    msg.pose.position.x = 3.0
    msg.pose.position.y = 4.0

    record = make_record_from_waterplus_message(
        msg,
        existing=[],
        default_frame_id="map",
    )

    assert record.name == "room_801"
    assert record.frame_id == "map"
    assert math.isclose(record.pose.position.x, 3.0)
    assert math.isclose(record.pose.position.y, 4.0)


def test_make_patrol_route_converts_records_to_ddsm_waypoints():
    record = WaterplusWaypointRecord(
        name="room_801",
        frame_id="map",
        pose=Pose(),
    )
    record.pose.position.x = 2.0
    record.pose.position.y = 1.0
    record.pose.orientation = yaw_to_quaternion(-0.5)

    route = make_patrol_route(
        [record],
        route_id="waterplus_route",
        loop=False,
        default_dwell_sec=5.0,
        default_waypoint_type="delivery_stop",
        default_final_approach=True,
    )

    assert route.route_id == "waterplus_route"
    assert route.loop is False
    assert len(route.waypoints) == 1
    assert route.waypoints[0].id == "room_801"
    assert route.waypoints[0].waypoint_type == "delivery_stop"
    assert route.waypoints[0].final_approach is True
    assert math.isclose(route.waypoints[0].yaw, -0.5)


def test_dump_waterplus_xml_matches_original_file_shape(tmp_path):
    record = WaterplusWaypointRecord(
        name="room_801",
        frame_id="map",
        pose=Pose(),
    )
    record.pose.position.x = 2.0
    record.pose.position.y = 1.0
    record.pose.orientation = yaw_to_quaternion(0.25)
    xml_path = tmp_path / "waypoints.xml"

    dump_waterplus_xml(xml_path, [record])

    root = ET.parse(xml_path).getroot()
    waypoint = root.find("Waypoint")
    assert root.tag == "Waterplus"
    assert waypoint.findtext("Name") == "room_801"
    assert waypoint.findtext("Pos_x") == "2.0"
    assert waypoint.findtext("Pos_y") == "1.0"
    assert waypoint.findtext("Ori_w") is not None


def test_find_waypoint_by_name_prefers_exact_then_substring():
    records = [
        WaterplusWaypointRecord(name="room_801", frame_id="map", pose=Pose()),
        WaterplusWaypointRecord(name="room_802", frame_id="map", pose=Pose()),
    ]

    assert find_waypoint_by_name(records, "room_802").name == "room_802"
    assert find_waypoint_by_name(records, "801").name == "room_801"
    assert find_waypoint_by_name(records, "missing") is None


def test_empty_route_start_is_rejected_without_persisting():
    from ddsm_car_control.waterplus_waypoint_bridge import WaterplusWaypointBridge

    class FakeBridge:
        records = []

        def __init__(self):
            self.statuses = []
            self.persisted = False
            self.started = False

        def publish_status(self, status):
            self.statuses.append(status)

        def get_logger(self):
            class Logger:
                def warn(self, _message):
                    pass

            return Logger()

        def persist(self):
            self.persisted = True

        class Publisher:
            def __init__(self, owner):
                self.owner = owner

            def publish(self, _message):
                self.owner.started = True

        @property
        def patrol_start_once_pub(self):
            return self.Publisher(self)

    bridge = FakeBridge()
    WaterplusWaypointBridge.on_start_once(bridge, None)

    assert bridge.statuses == ["route_empty"]
    assert bridge.persisted is False
    assert bridge.started is False
