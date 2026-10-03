from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict

import yaml


@dataclass(frozen=True)
class FloorTarget:
    floor_id: str
    map_file: str
    semantic_manifest_file: str
    patrol_route_file: str
    destination_key: str
    destination_id: str
    initial_x: float
    initial_y: float
    initial_yaw: float
    target_x: float
    target_y: float
    target_yaw: float


@dataclass(frozen=True)
class TransferState:
    phase: str = "idle"
    floor_id: str = ""
    map_file: str = ""
    semantic_manifest_file: str = ""
    patrol_route_file: str = ""
    destination_key: str = ""
    destination_id: str = ""
    initial_x: float = 0.0
    initial_y: float = 0.0
    initial_yaw: float = 0.0
    target_x: float = 0.0
    target_y: float = 0.0
    target_yaw: float = 0.0


def load_floor_target(path: str, floor_id: str, destination: str = "") -> FloorTarget:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    floors: Dict[str, Any] = data.get("floors") or {}
    destinations: Dict[str, Any] = data.get("destinations") or {}
    floor = floors.get(floor_id)
    if not isinstance(floor, dict):
        raise ValueError(f"unknown target floor {floor_id!r}")

    query = str(destination or "").strip()
    candidates = []
    for key, spec in destinations.items():
        if not isinstance(spec, dict) or str(spec.get("floor_id")) != floor_id:
            continue
        labels = {
            str(key).casefold(),
            str(spec.get("destination_id") or "").casefold(),
            str(spec.get("display_name") or "").casefold(),
        }
        if query and query.casefold() in labels:
            candidates = [(key, spec)]
            break
        candidates.append((key, spec))

    if query and len(candidates) != 1:
        matched = [
            item
            for item in candidates
            if query.casefold()
            in {
                str(item[0]).casefold(),
                str(item[1].get("destination_id") or "").casefold(),
                str(item[1].get("display_name") or "").casefold(),
            }
        ]
        if len(matched) == 1:
            candidates = matched
    if not query:
        door_key = f"floor{floor_id.split('_')[-1]}_door"
        door = [(key, spec) for key, spec in candidates if key == door_key]
        candidates = door or candidates[:1]
    if len(candidates) != 1:
        available = [key for key, _ in candidates]
        raise ValueError(
            f"destination {destination!r} is not unique on {floor_id}; available={available}"
        )

    key, destination_spec = candidates[0]
    manifest_path = Path(str(floor["semantic_map"]))
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    poi_path = manifest_path.parent / str(manifest["poi_database"])
    poi_document = yaml.safe_load(poi_path.read_text(encoding="utf-8")) or {}
    poi = next(
        (
            item
            for item in (poi_document.get("pois") or [])
            if isinstance(item, dict)
            and str(item.get("id") or "")
            == str(destination_spec["destination_id"])
        ),
        None,
    )
    if poi is None:
        raise ValueError(
            f"destination {destination_spec['destination_id']!r} has no POI on {floor_id}"
        )
    elevator_id = str(data.get("default_elevator_id") or "elevator_A")
    elevators = floor.get("elevator_poses") or {}
    elevator = elevators.get(elevator_id) or {}
    pose = elevator.get("exit_initial_pose") or {}
    return FloorTarget(
        floor_id=floor_id,
        map_file=str(floor["map"]),
        semantic_manifest_file=str(manifest_path.resolve()),
        patrol_route_file=str(floor.get("patrol_route") or ""),
        destination_key=str(key),
        destination_id=str(destination_spec["destination_id"]),
        initial_x=float(pose["x"]),
        initial_y=float(pose["y"]),
        initial_yaw=float(pose["yaw"]),
        target_x=float(poi["x"]),
        target_y=float(poi["y"]),
        target_yaw=float(poi["yaw"]),
    )


def state_from_target(target: FloorTarget, phase: str) -> TransferState:
    return TransferState(
        phase=phase,
        floor_id=target.floor_id,
        map_file=target.map_file,
        semantic_manifest_file=target.semantic_manifest_file,
        patrol_route_file=target.patrol_route_file,
        destination_key=target.destination_key,
        destination_id=target.destination_id,
        initial_x=target.initial_x,
        initial_y=target.initial_y,
        initial_yaw=target.initial_yaw,
        target_x=target.target_x,
        target_y=target.target_y,
        target_yaw=target.target_yaw,
    )


def save_transfer_state(path: str, state: TransferState) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        yaml.safe_dump(asdict(state), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def save_initial_pose_file(path: str, target: FloorTarget) -> None:
    pose = {
        "configured": True,
        "x": target.initial_x,
        "y": target.initial_y,
        "yaw": target.initial_yaw,
        "map_file": target.map_file,
    }
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        yaml.safe_dump(pose, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def load_transfer_state(path: str) -> TransferState:
    source = Path(path)
    if not source.exists():
        return TransferState()
    data = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return TransferState()
    values = {field: data.get(field, default) for field, default in asdict(TransferState()).items()}
    return TransferState(**values)
