from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "perception/object_api"))

from backend_policy import can_promote, promotion_decision


class ObjectCapabilityPreservationTest(unittest.TestCase):
    def test_person_only_provider_cannot_replace_open_vocabulary(self):
        provider = {
            "s100_supported": True,
            "api_compatible": True,
            "onsite_accuracy_not_worse": True,
            "realtime_ok": True,
            "text_open_vocabulary": False,
            "dynamic_multi_class": False,
        }
        self.assertFalse(can_promote("open_vocabulary_search", provider))
        decision = promotion_decision("open_vocabulary_search", provider)
        self.assertIn("text_open_vocabulary", decision["blockers"])
        self.assertIn("dynamic_multi_class", decision["blockers"])

    def test_recorded_search_requires_recording_capability(self):
        provider = {
            "s100_supported": True,
            "api_compatible": True,
            "onsite_accuracy_not_worse": True,
            "realtime_ok": True,
            "text_open_vocabulary": True,
            "dynamic_multi_class": True,
            "recorded_video_search": False,
        }
        self.assertFalse(can_promote("recorded_video_search", provider))

    def test_full_equivalence_can_promote(self):
        provider = {
            "s100_supported": True,
            "api_compatible": True,
            "onsite_accuracy_not_worse": True,
            "realtime_ok": True,
            "text_open_vocabulary": True,
            "dynamic_multi_class": True,
            "recorded_video_search": True,
        }
        self.assertTrue(can_promote("recorded_video_search", provider))

    def test_product_modules_are_preserved(self):
        required = [
            ROOT / "perception/yoloe26_live/yoloe26_live_api.py",
            ROOT / "perception/locateanything_trial_20260907",
            ROOT / "perception/spatial_memory",
            ROOT / "perception/object_api/s100_object_api.py",
        ]
        for path in required:
            with self.subTest(path=path):
                self.assertTrue(path.exists())

    def test_object_api_compatibility_endpoints_remain(self):
        text = (ROOT / "perception/object_api/s100_object_api.py").read_text(
            encoding="utf-8")
        for endpoint in ("/health", "/model/unload", "/infer_image"):
            self.assertIn(endpoint, text)


if __name__ == "__main__":
    unittest.main()
