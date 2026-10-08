"""Domain models for hotel semantic maps."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class MapIdentity:
    site_id: str
    floor_id: str
    map_id: str
    map_version: str
    frame_id: str


@dataclass(frozen=True)
class Poi:
    id: str
    display_name: str
    poi_type: str
    floor_id: str
    area_id: str
    x: float
    y: float
    yaw: float
    final_approach_profile: str
    enabled: bool
    map_version: str

    def validate(self, identity: MapIdentity) -> None:
        if self.floor_id != identity.floor_id:
            raise ValueError("floor_id does not match map identity")
        if self.map_version != identity.map_version:
            raise ValueError("map_version does not match map identity")


@dataclass(frozen=True)
class SemanticArea:
    id: str
    display_name: str
    area_type: str
    floor_id: str
    priority: int
    geometry: Any


@dataclass(frozen=True)
class MapManifest:
    identity: MapIdentity
    manifest_path: Path
    occupancy_map: Path
    semantic_areas: Path
    route_graph: Path
    poi_database: Path
    checksums_file: Path


@dataclass(frozen=True)
class ResolvedDestination:
    poi: Poi
    matched_by: str
