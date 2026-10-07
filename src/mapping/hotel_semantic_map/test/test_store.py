from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hotel_semantic_map.models import SemanticArea
from hotel_semantic_map.store import (
    area_contains,
    find_area,
    load_semantic_map,
    parse_floor_context,
    point_in_ring,
    resolve_destination,
)


PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def test_floor_context_requires_and_preserves_floor_manifest():
    context = parse_floor_context(
        '{"floor_id":"floor_2","semantic_manifest_file":"/maps/floor_2/map_manifest.yaml",'
        '"map_file":"/maps/floor_2.yaml","source":"test"}'
    )
    assert context.floor_id == "floor_2"
    assert context.semantic_manifest_file.endswith("floor_2/map_manifest.yaml")
    assert context.source == "test"


def test_example_semantic_map_loads():
    data = load_semantic_map(PACKAGE_ROOT / "config" / "map_manifest.yaml")

    assert data.identity.frame_id == "map"
    assert data.identity.floor_id == "floor_1"
    assert len(data.areas) == 1
    assert {poi.id for poi in data.pois} == {
        "home",
        "wp_001",
        "wp_002",
        "wp_003",
        "wp_004",
    }


def test_point_in_ring_includes_boundary():
    ring = [[0.0, 0.0], [2.0, 0.0], [2.0, 2.0], [0.0, 2.0], [0.0, 0.0]]

    assert point_in_ring(1.0, 1.0, ring)
    assert point_in_ring(0.0, 1.0, ring)
    assert not point_in_ring(3.0, 1.0, ring)


def test_polygon_hole_is_not_inside():
    area = SemanticArea(
        id="test",
        display_name="Test",
        area_type="general",
        floor_id="floor_1",
        priority=0,
        geometry={
            "type": "Polygon",
            "coordinates": [
                [[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]],
                [[1, 1], [3, 1], [3, 3], [1, 3], [1, 1]],
            ],
        },
    )

    assert area_contains(area, 0.5, 0.5)
    assert not area_contains(area, 2.0, 2.0)


def test_highest_priority_area_wins():
    geometry = {
        "type": "Polygon",
        "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]],
    }
    general = SemanticArea("general", "General", "general", "floor_1", 0, geometry)
    restricted = SemanticArea(
        "restricted", "Restricted", "restricted", "floor_1", 10, geometry
    )

    assert find_area([general, restricted], 1.0, 1.0) == restricted


def test_destination_resolves_by_id_and_display_name():
    data = load_semantic_map(PACKAGE_ROOT / "config" / "map_manifest.yaml")
    target = next(poi for poi in data.pois if poi.id == "wp_001")

    assert resolve_destination(data.pois, "wp_001").matched_by == "id"
    resolved = resolve_destination(data.pois, f" {target.display_name} ")
    assert resolved.poi.id == "wp_001"
    assert resolved.matched_by == "display_name"
    assert resolve_destination(data.pois, "missing") is None
