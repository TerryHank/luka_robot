import unittest
import threading
from unittest.mock import Mock
import numpy as np

from person_follow.vision import FaceFeatures, decode_coco_people, estimate_person_geometry, face_pose_quality


class PersonDecodeTests(unittest.TestCase):
    def test_letterbox_and_person_class_filter_and_nms(self):
        raw = np.zeros((1, 84, 4), dtype=np.float32)
        # A 640x480 image is padded by 80 pixels above and below.
        raw[0, :4, 0] = [300, 320, 100, 240]
        raw[0, 4, 0] = .8
        raw[0, :4, 1] = [301, 320, 100, 240]
        raw[0, 4, 1] = .7
        raw[0, :4, 2] = [100, 320, 100, 200]
        raw[0, 4, 2], raw[0, 6, 2] = .6, .9  # Another class wins.
        raw[0, :4, 3] = [450, 320, 80, 160]
        raw[0, 4, 3] = .2
        result = decode_coco_people(raw, (480, 640, 3))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["bbox"], [250, 120, 350, 360])
        self.assertAlmostEqual(result[0]["confidence"], .8)

    def test_refuses_household_or_nms_engine(self):
        for raw in (np.zeros((1, 74, 8400)), np.zeros((1, 300, 6))):
            with self.assertRaises(ValueError):
                decode_coco_people(raw, (480, 640))

    def test_empty_or_nonfinite_candidates(self):
        raw = np.full((1, 84, 2), np.nan)
        self.assertEqual(decode_coco_people(raw, (480, 640)), [])


class DepthTests(unittest.TestCase):
    def setUp(self):
        self.depth = np.full((480, 640), 2., np.float32)
        self.box = [200, 40, 400, 440]
        self.k = {"fx": 500, "cx": 320}

    def test_torso_uses_distance_not_background_between_legs(self):
        self.depth[300:] = 4.5
        result = estimate_person_geometry(self.depth, self.box, self.k)
        self.assertTrue(result["valid"])
        self.assertAlmostEqual(result["distance_m"], 2.)
        self.assertLess(result["bearing_rad"], 0.)

    def test_no_depth_or_out_of_range_never_yields_zero(self):
        for invalid in (0., np.nan, 10.):
            result = estimate_person_geometry(np.full_like(self.depth, invalid), self.box, self.k)
            self.assertFalse(result["valid"])
            self.assertIsNone(result["distance_m"])

    def test_uint16_depth_requires_explicit_conversion(self):
        result = estimate_person_geometry(np.full((480, 640), 2000, np.uint16), self.box, self.k)
        self.assertEqual(result["reason"], "depth_must_be_float_metres")

    def test_ambiguous_foreground_and_background_is_unknown(self):
        self.depth[:, 300:] = 4.
        result = estimate_person_geometry(self.depth, self.box, self.k)
        self.assertEqual(result["reason"], "ambiguous_depth_layers")
        self.assertFalse(result["valid"])

    def test_sparse_holes_and_outliers_tolerated(self):
        self.depth[::4, ::4] = np.nan
        self.depth[::8, ::8] = .3
        result = estimate_person_geometry(self.depth, self.box, self.k)
        self.assertTrue(result["valid"])
        self.assertAlmostEqual(result["distance_m"], 2.)

    def test_clipped_person_and_unsynced_frames_rejected(self):
        result = estimate_person_geometry(self.depth, [200, 0, 400, 440], self.k)
        self.assertEqual(result["reason"], "person_upper_body_clipped")
        result = estimate_person_geometry(self.depth, self.box, self.k, skew_s=.3)
        self.assertEqual(result["reason"], "rgb_depth_not_synchronized")

    def test_bad_intrinsics(self):
        result = estimate_person_geometry(self.depth, self.box, {"fx": 0, "cx": 320})
        self.assertFalse(result["valid"])

    def test_orbbec_intrinsic_key_names(self):
        result = estimate_person_geometry(self.depth, self.box, {"fX": 500, "cX": 320})
        self.assertTrue(result["valid"])


class FaceQualityTests(unittest.TestCase):
    def setUp(self):
        self.face = np.array([20, 20, 100, 120, 45, 55, 95, 55,
                              70, 85, 50, 110, 90, 110, .98], dtype=float)

    def test_frontal_clear_face(self):
        quality, reason = face_pose_quality(self.face, (200, 200, 3))
        self.assertEqual(reason, "ok")
        self.assertGreater(quality, .9)

    def test_sideways_or_small_face_cannot_identify(self):
        sideways = self.face.copy()
        sideways[8] = 92
        self.assertEqual(face_pose_quality(sideways, (200, 200))[1], "face_not_frontal")
        tiny = self.face.copy()
        tiny[2] = 30
        self.assertEqual(face_pose_quality(tiny, (200, 200))[1], "face_too_small")

    def test_clipped_face(self):
        self.face[0] = 0
        self.assertEqual(face_pose_quality(self.face, (200, 200))[1], "face_clipped")

    def test_multiple_faces_never_generate_identity_embedding(self):
        extractor = FaceFeatures.__new__(FaceFeatures)
        extractor.lock = threading.Lock()
        extractor.min_face_px = 64
        extractor.detector = Mock()
        extractor.recognizer = Mock()
        extractor.detector.detect.return_value = (1, np.stack([self.face, self.face]))
        result = extractor.face_features(np.zeros((480, 640, 3), np.uint8), [100, 20, 400, 460])
        self.assertFalse(result["accepted"])
        self.assertEqual(result["reason"], "multiple_faces_in_body")
        self.assertIsNone(result["embedding"])
        extractor.recognizer.feature.assert_not_called()

    def test_no_visible_face_remains_unknown(self):
        extractor = FaceFeatures.__new__(FaceFeatures)
        extractor.lock = threading.Lock()
        extractor.min_face_px = 64
        extractor.detector = Mock()
        extractor.detector.detect.return_value = (1, None)
        result = extractor.face_features(np.zeros((480, 640, 3), np.uint8), [100, 20, 400, 460])
        self.assertFalse(result["accepted"])
        self.assertEqual(result["reason"], "no_face")
        self.assertIsNone(result["embedding"])


if __name__ == "__main__":
    unittest.main()
