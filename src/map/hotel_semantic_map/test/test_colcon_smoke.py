from pathlib import Path
import unittest

from hotel_semantic_map.store import load_semantic_map


class SemanticMapColconSmokeTest(unittest.TestCase):
    def test_packaged_example_loads(self):
        manifest = Path(__file__).resolve().parents[1] / "config" / "map_manifest.yaml"
        data = load_semantic_map(manifest)

        self.assertEqual(data.identity.frame_id, "map")
        self.assertGreater(len(data.areas), 0)
        self.assertGreater(len(data.pois), 0)


if __name__ == "__main__":
    unittest.main()
