"""Load and query a versioned hotel semantic-map data set."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Sequence

import yaml

from .models import MapIdentity, Poi, ResolvedDestination, SemanticArea


@dataclass(frozen=True)
class SemanticMapData:
    identity: MapIdentity
    areas: tuple[SemanticArea, ...]
    pois: tuple[Poi, ...]


@dataclass(frozen=True)
class FloorContext:
    floor_id: str
    semantic_manifest_file: str
    map_file: str = ""
    patrol_route_file: str = ""
    source: str = ""


def parse_floor_context(value: str) -> FloorContext:
    document = json.loads(value)
    if not isinstance(document, dict):
        raise ValueError("floor context must be a JSON object")
    floor_id = str(document.get("floor_id") or "").strip()
    manifest = str(document.get("semantic_manifest_file") or "").strip()
    if not floor_id:
        raise ValueError("floor_id is required")
    if not manifest:
        raise ValueError("semantic_manifest_file is required")
    return FloorContext(
        floor_id=floor_id,
        semantic_manifest_file=manifest,
        map_file=str(document.get("map_file") or "").strip(),
        patrol_route_file=str(document.get("patrol_route_file") or "").strip(),
        source=str(document.get("source") or "").strip(),
    )


def _required(mapping: dict, key: str, source: Path):
    if key not in mapping:
        raise ValueError(f"missing '{key}' in {source}")
    return mapping[key]


def _resolve_data_path(manifest_path: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else manifest_path.parent / path


def _load_areas(path: Path, identity: MapIdentity) -> tuple[SemanticArea, ...]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("type") != "FeatureCollection":
        raise ValueError(f"{path} must be a GeoJSON FeatureCollection")

    areas = []
    seen_ids = set()
    for index, feature in enumerate(document.get("features", [])):
        geometry = feature.get("geometry") or {}
        if geometry.get("type") not in {"Polygon", "MultiPolygon"}:
            raise ValueError(f"area feature {index} must be Polygon or MultiPolygon")
        properties = feature.get("properties") or {}
        area_id = str(_required(properties, "id", path))
        if area_id in seen_ids:
            raise ValueError(f"duplicate area id '{area_id}' in {path}")
        seen_ids.add(area_id)
        floor_id = str(properties.get("floor_id", identity.floor_id))
        if floor_id != identity.floor_id:
            raise ValueError(f"area '{area_id}' belongs to floor '{floor_id}'")
        areas.append(
            SemanticArea(
                id=area_id,
                display_name=str(properties.get("display_name", area_id)),
                area_type=str(properties.get("area_type", "general")),
                floor_id=floor_id,
                priority=int(properties.get("priority", 0)),
                geometry=geometry,
            )
        )
    return tuple(areas)


def _load_pois(path: Path, identity: MapIdentity) -> tuple[Poi, ...]:
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = document.get("pois", []) if isinstance(document, dict) else document
    if not isinstance(entries, list):
        raise ValueError(f"{path} must contain a 'pois' list")

    pois = []
    seen_ids = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"POI entry {index} in {path} must be a mapping")
        poi_id = str(_required(entry, "id", path))
        if poi_id in seen_ids:
            raise ValueError(f"duplicate POI id '{poi_id}' in {path}")
        seen_ids.add(poi_id)
        poi = Poi(
            id=poi_id,
            display_name=str(entry.get("display_name", poi_id)),
            poi_type=str(entry.get("poi_type", "waypoint")),
            floor_id=str(entry.get("floor_id", identity.floor_id)),
            area_id=str(entry.get("area_id", "")),
            x=float(_required(entry, "x", path)),
            y=float(_required(entry, "y", path)),
            yaw=float(entry.get("yaw", 0.0)),
            final_approach_profile=str(entry.get("final_approach_profile", "none")),
            enabled=bool(entry.get("enabled", True)),
            map_version=str(entry.get("map_version", identity.map_version)),
        )
        poi.validate(identity)
        pois.append(poi)
    return tuple(pois)


def load_semantic_map(manifest_file: str | Path) -> SemanticMapData:
    manifest_path = Path(manifest_file).expanduser().resolve()
    document = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    if not isinstance(document, dict):
        raise ValueError(f"{manifest_path} must contain a YAML mapping")

    identity = MapIdentity(
        site_id=str(_required(document, "site_id", manifest_path)),
        floor_id=str(_required(document, "floor_id", manifest_path)),
        map_id=str(_required(document, "map_id", manifest_path)),
        map_version=str(_required(document, "map_version", manifest_path)),
        frame_id=str(document.get("frame_id", "map")),
    )
    areas_path = _resolve_data_path(
        manifest_path, str(_required(document, "semantic_areas", manifest_path))
    )
    pois_path = _resolve_data_path(
        manifest_path, str(_required(document, "poi_database", manifest_path))
    )
    areas = _load_areas(areas_path, identity)
    pois = _load_pois(pois_path, identity)
    area_ids = {area.id for area in areas}
    for poi in pois:
        if poi.area_id and poi.area_id not in area_ids:
            raise ValueError(f"POI '{poi.id}' references unknown area '{poi.area_id}'")
    return SemanticMapData(identity=identity, areas=areas, pois=pois)


def _point_on_segment(
    x: float,
    y: float,
    first: Sequence[float],
    second: Sequence[float],
    epsilon: float = 1.0e-9,
) -> bool:
    x1, y1 = float(first[0]), float(first[1])
    x2, y2 = float(second[0]), float(second[1])
    cross = (x - x1) * (y2 - y1) - (y - y1) * (x2 - x1)
    if abs(cross) > epsilon:
        return False
    dot = (x - x1) * (x - x2) + (y - y1) * (y - y2)
    return dot <= epsilon


def point_in_ring(x: float, y: float, ring: Sequence[Sequence[float]]) -> bool:
    if len(ring) < 3:
        return False
    inside = False
    previous = ring[-1]
    for current in ring:
        if _point_on_segment(x, y, previous, current):
            return True
        x1, y1 = float(previous[0]), float(previous[1])
        x2, y2 = float(current[0]), float(current[1])
        if (y1 > y) != (y2 > y):
            intersection_x = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < intersection_x:
                inside = not inside
        previous = current
    return inside


def _point_in_polygon(x: float, y: float, polygon: Sequence) -> bool:
    if not polygon or not point_in_ring(x, y, polygon[0]):
        return False
    return not any(point_in_ring(x, y, hole) for hole in polygon[1:])


def area_contains(area: SemanticArea, x: float, y: float) -> bool:
    geometry = area.geometry
    coordinates = geometry.get("coordinates", [])
    if geometry.get("type") == "Polygon":
        return _point_in_polygon(x, y, coordinates)
    if geometry.get("type") == "MultiPolygon":
        return any(_point_in_polygon(x, y, polygon) for polygon in coordinates)
    return False


def find_area(
    areas: Iterable[SemanticArea], x: float, y: float
) -> Optional[SemanticArea]:
    matches = [area for area in areas if area_contains(area, x, y)]
    if not matches:
        return None
    return max(matches, key=lambda area: area.priority)


def _normalize_name(value: str) -> str:
    return "".join(character.casefold() for character in value.strip() if not character.isspace())


def resolve_destination(
    pois: Iterable[Poi], query: str, floor_id: str = ""
) -> Optional[ResolvedDestination]:
    candidates = [
        poi
        for poi in pois
        if poi.enabled and (not floor_id or poi.floor_id == floor_id)
    ]
    normalized = _normalize_name(query)
    for poi in candidates:
        if _normalize_name(poi.id) == normalized:
            return ResolvedDestination(poi=poi, matched_by="id")
    for poi in candidates:
        if _normalize_name(poi.display_name) == normalized:
            return ResolvedDestination(poi=poi, matched_by="display_name")
    return None
