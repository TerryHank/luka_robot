import math
from pathlib import Path

from geometry_msgs.msg import PoseStamped

from ddsm_car_control.ddsm_patrol_manager import (
    PatrolCursor,
    PatrolRoute,
    Waypoint,
    append_pose_waypoint,
    classify_final_approach_status,
    dump_route,
    load_route,
    make_route_markers,
    make_route_path,
    safe_service_is_ready,
    waypoint_requires_final_approach,
    yaw_to_quaternion,
)


def test_load_route_marks_delivery_stops_for_final_approach(tmp_path):
    route_file = tmp_path / "patrol_route.yaml"
    route_file.write_text(
        """
route_id: floor_1
loop: true
waypoints:
  - id: lobby
    name: Lobby
    x: 1.0
    y: 2.0
    yaw: 0.0
    type: pass
  - id: room_801
    name: Room 801
    x: 3.0
    y: 4.0
    yaw: 1.57
    type: delivery_stop
    dwell_sec: 8
""",
        encoding="utf-8",
    )

    route = load_route(route_file)

    assert route.route_id == "floor_1"
    assert route.loop is True
    assert len(route.waypoints) == 2
    assert route.waypoints[1].id == "room_801"
    assert route.waypoints[1].dwell_sec == 8.0
    assert waypoint_requires_final_approach(route.waypoints[1])


def test_dump_route_round_trip_preserves_waypoint_metadata(tmp_path):
    route = PatrolRoute(
        route_id="delivery_loop",
        loop=True,
        waypoints=[
            Waypoint(
                id="room_802",
                name="Room 802",
                x=2.4,
                y=-0.6,
                yaw=-0.3,
                waypoint_type="delivery_stop",
                dwell_sec=5.0,
                final_approach=True,
            )
        ],
    )
    route_file = tmp_path / "route.yaml"

    dump_route(route_file, route)
    loaded = load_route(route_file)

    assert loaded == route


def test_append_pose_waypoint_generates_route_path():
    route = PatrolRoute(route_id="manual", loop=False, waypoints=[])
    pose = PoseStamped()
    pose.header.frame_id = "map"
    pose.pose.position.x = 1.25
    pose.pose.position.y = -2.5
    pose.pose.orientation = yaw_to_quaternion(math.pi / 2.0)

    waypoint = append_pose_waypoint(route, pose, default_dwell_sec=3.0)
    path = make_route_path(route, frame_id="map")

    assert waypoint.id == "wp_001"
    assert waypoint.name == "wp_001"
    assert math.isclose(waypoint.x, 1.25)
    assert math.isclose(waypoint.y, -2.5)
    assert math.isclose(waypoint.yaw, math.pi / 2.0)
    assert waypoint.dwell_sec == 3.0
    assert len(path.poses) == 1
    assert path.poses[0].header.frame_id == "map"


def test_patrol_cursor_advances_once_and_loops():
    single_run = PatrolCursor(route_len=2, loop=False)

    assert single_run.current_index == 0
    assert single_run.advance() == 1
    assert single_run.advance() is None

    loop_run = PatrolCursor(route_len=2, loop=True)

    assert loop_run.advance() == 1
    assert loop_run.advance() == 0


def test_final_approach_status_classification():
    assert classify_final_approach_status("final_reached") == "success"
    assert classify_final_approach_status("final_servo") == "pending"
    assert classify_final_approach_status("blocked_front:0.24") == "failure"
    assert classify_final_approach_status("final_servo_timeout") == "failure"
    assert classify_final_approach_status("staging_failed:6") == "failure"


def test_route_markers_include_current_waypoint_highlight():
    route = PatrolRoute(
        route_id="markers",
        loop=False,
        waypoints=[
            Waypoint(id="a", name="A", x=0.0, y=0.0, yaw=0.0),
            Waypoint(id="b", name="B", x=1.0, y=0.0, yaw=0.0),
        ],
    )

    markers = make_route_markers(route, frame_id="map", current_index=1)

    assert len(markers.markers) == 4
    assert markers.markers[0].header.frame_id == "map"
    assert markers.markers[3].text == "B"
    assert markers.markers[3].color.r > markers.markers[0].color.r


def test_safe_service_is_ready_skips_when_context_is_down():
    class FakeClient:
        def service_is_ready(self):
            raise AssertionError("service_is_ready should not be called")

    assert safe_service_is_ready(FakeClient(), context_ok=False) is False


def test_safe_service_is_ready_handles_rcl_context_errors():
    class FakeClient:
        def service_is_ready(self):
            raise RuntimeError("rcl node's context is invalid")

    assert safe_service_is_ready(FakeClient(), context_ok=True) is False
