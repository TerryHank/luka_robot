from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def test_required_interfaces_match_contract():
    expected = {
        "msg/Destination.msg": [
            "string id",
            "string display_name",
            "string poi_type",
            "string floor_id",
            "string area_id",
            "geometry_msgs/Pose pose",
            "string final_approach_profile",
            "bool enabled",
        ],
        "msg/SemanticMapStatus.msg": [
            "std_msgs/Header header",
            "string site_id",
            "string floor_id",
            "string map_version",
            "bool ready",
            "string message",
        ],
        "srv/ListDestinations.srv": [
            "string floor_id",
            "string poi_type",
            "bool enabled_only",
            "---",
            "hotel_semantic_map_msgs/Destination[] destinations",
        ],
        "srv/ResolveDestination.srv": [
            "string query",
            "string floor_id",
            "---",
            "bool success",
            "hotel_semantic_map_msgs/Destination destination",
            "string error_code",
            "string message",
        ],
        "srv/GetCurrentArea.srv": [
            "geometry_msgs/PoseStamped pose",
            "---",
            "bool success",
            "string area_id",
            "string display_name",
            "string area_type",
            "string error_code",
            "string message",
        ],
        "action/NavigateToNamedDestination.action": [
            "string map_version",
            "string destination_id",
            "bool use_final_approach",
            "string request_id",
            "---",
            "bool success",
            "string resolved_destination_id",
            "string failure_code",
            "string message",
            "---",
            "string phase",
            "string current_area_id",
            "float32 distance_remaining",
        ],
    }

    for relative_path, expected_lines in expected.items():
        actual_lines = [
            line.strip()
            for line in (PACKAGE_ROOT / relative_path).read_text().splitlines()
            if line.strip()
        ]
        assert actual_lines == expected_lines, relative_path
