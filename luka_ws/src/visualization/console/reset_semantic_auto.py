#!/usr/bin/env python3

import argparse
import os
import shutil
import tempfile
import time
from pathlib import Path

import yaml


GENERATOR = "ddsm_car_control/semantic_mapping_recorder"


def atomic_yaml(path: Path, payload: dict) -> None:
    handle, temp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            yaml.safe_dump(payload, stream, allow_unicode=True, sort_keys=False)
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("workspace", type=Path)
    args = parser.parse_args()

    workspace = args.workspace.resolve()
    detections_path = workspace / "src/common/config/semantic_auto/floor_1/detections.yaml"
    pois_path = workspace / "src/common/config/semantic/floor_1/pois.yaml"
    stamp = time.strftime("%Y%m%d_%H%M%S")

    detections = yaml.safe_load(detections_path.read_text(encoding="utf-8")) or {}
    pois = yaml.safe_load(pois_path.read_text(encoding="utf-8")) or {}
    old_objects = list(detections.get("objects", []))
    old_pois = list(pois.get("pois", []))
    manual_pois = [item for item in old_pois if item.get("generated_by") != GENERATOR]
    auto_pois = [item for item in old_pois if item.get("generated_by") == GENERATOR]

    detections_backup = detections_path.with_name(detections_path.name + f".bak_{stamp}")
    pois_backup = pois_path.with_name(pois_path.name + f".bak_{stamp}")
    shutil.copy2(detections_path, detections_backup)
    shutil.copy2(pois_path, pois_backup)

    detections["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    detections["objects"] = []
    detections["rooms"] = []
    detections["note"] = "Auto detections reset before RKNN recognition restart."
    atomic_yaml(detections_path, detections)
    atomic_yaml(pois_path, {"pois": manual_pois})

    print(f"objects_removed={len(old_objects)}")
    print(f"auto_pois_removed={len(auto_pois)}")
    print(f"manual_pois_preserved={len(manual_pois)}")
    print(f"detections_backup={detections_backup}")
    print(f"pois_backup={pois_backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
