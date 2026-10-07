"""Pure schema checks for the P3 ROS person observation contract."""
from __future__ import annotations

import ast
from pathlib import Path
import unittest


MODULE = Path(__file__).resolve().parents[2] / "perception/person_follow/ros_observation_publisher.py"


def load_build_target_specs():
    """Load only the pure helper without requiring rclpy on host-side CI."""
    source = MODULE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    keep = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            # The pure helper needs only math; deliberately skip ROS imports.
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            if names == ["math"]:
                keep.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in ("_finite", "build_target_specs"):
            keep.append(node)
    module = ast.Module(body=keep, type_ignores=[])
    scope = {}
    exec(compile(module, str(MODULE), "exec"), scope)
    return scope["build_target_specs"]


build_target_specs = load_build_target_specs()


class PersonObservationSchemaTest(unittest.TestCase):
    def test_geometry_and_privacy_minimization(self):
        snapshot = {"tracks": [{
            "track_id": 7,
            "bbox": [10, 20, 110, 220],
            "confidence": .91,
            "depth_valid": True,
            "observation_strength": "strong",
            "association_ambiguous": False,
            "visible": True,
            "identity": {"name": "must-not-leak"},
            "depth_diagnostic": {
                "position_optical_m": [.1, -.2, 2.5],
                "width_m": .6,
                "height_m": 1.7,
                "valid_fraction": .9,
                "rgb_depth_skew_s": .02,
            },
        }]}
        specs = build_target_specs(snapshot)
        self.assertEqual(len(specs), 1)
        self.assertEqual(specs[0]["track_id"], 7)
        self.assertEqual(specs[0]["bbox"], [10, 20, 110, 220])
        self.assertAlmostEqual(specs[0]["attributes"]["optical_z_m"], 2.5)
        self.assertNotIn("identity", specs[0])
        self.assertNotIn("name", specs[0])

    def test_invalid_box_is_dropped(self):
        self.assertEqual(build_target_specs({
            "tracks": [{"track_id": 1, "bbox": [10, 10, 5, 5]}]
        }), [])


if __name__ == "__main__":
    unittest.main()
