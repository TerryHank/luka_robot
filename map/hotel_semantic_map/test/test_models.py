from dataclasses import FrozenInstanceError
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hotel_semantic_map.models import (
    MapIdentity,
    MapManifest,
    Poi,
    ResolvedDestination,
    SemanticArea,
)


@pytest.fixture
def identity() -> MapIdentity:
    return MapIdentity(
        site_id="hotel-a",
        floor_id="floor-1",
        map_id="main",
        map_version="2026.07",
        frame_id="map",
    )


@pytest.fixture
def poi() -> Poi:
    return Poi(
        id="room-101",
        display_name="Room 101",
        poi_type="guest_room",
        floor_id="floor-1",
        area_id="east-wing",
        x=1.5,
        y=2.5,
        yaw=0.0,
        final_approach_profile="doorway",
        enabled=True,
        map_version="2026.07",
    )


def test_models_are_frozen(identity: MapIdentity, poi: Poi, tmp_path: Path):
    models = [
        identity,
        poi,
        SemanticArea("lobby", "Lobby", "public", "floor-1", 10, {}),
        MapManifest(
            identity,
            tmp_path / "manifest.yaml",
            tmp_path / "map.yaml",
            tmp_path / "areas.geojson",
            tmp_path / "routes.yaml",
            tmp_path / "pois.yaml",
            tmp_path / "checksums.txt",
        ),
        ResolvedDestination(poi, "id"),
    ]

    for model in models:
        with pytest.raises(FrozenInstanceError):
            model.id = "changed"


def test_poi_rejects_mismatched_floor_id(identity: MapIdentity, poi: Poi):
    mismatched = Poi(**{**poi.__dict__, "floor_id": "floor-2"})

    with pytest.raises(ValueError, match="floor_id"):
        mismatched.validate(identity)


def test_poi_rejects_mismatched_map_version(identity: MapIdentity, poi: Poi):
    mismatched = Poi(**{**poi.__dict__, "map_version": "2026.08"})

    with pytest.raises(ValueError, match="map_version"):
        mismatched.validate(identity)


def test_poi_accepts_matching_identity(identity: MapIdentity, poi: Poi):
    assert poi.validate(identity) is None


def test_manifest_path_fields_remain_paths(identity: MapIdentity, tmp_path: Path):
    paths = [
        tmp_path / "manifest.yaml",
        tmp_path / "map.yaml",
        tmp_path / "areas.geojson",
        tmp_path / "routes.yaml",
        tmp_path / "pois.yaml",
        tmp_path / "checksums.txt",
    ]
    manifest = MapManifest(identity, *paths)

    assert [
        manifest.manifest_path,
        manifest.occupancy_map,
        manifest.semantic_areas,
        manifest.route_graph,
        manifest.poi_database,
        manifest.checksums_file,
    ] == paths
    assert all(isinstance(path, Path) for path in paths)


def test_resolved_destination_composes_poi(poi: Poi):
    resolved = ResolvedDestination(poi=poi, matched_by="display_name")

    assert resolved.poi is poi
    assert resolved.matched_by == "display_name"
