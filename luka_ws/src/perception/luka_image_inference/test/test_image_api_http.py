import base64
import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

import cv2
import numpy as np
from luka_image_inference import api


class ImageApiTests(unittest.TestCase):
    def setUp(self):
        self.saved = api.detector
        api.detector = None
        self.server = api.ThreadingHTTPServer(('127.0.0.1', 0), api.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.root = 'http://127.0.0.1:%s' % self.server.server_port
        ok, data = cv2.imencode('.jpg', np.zeros((64, 64, 3), np.uint8))
        assert ok
        self.image = base64.b64encode(data).decode()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        api.detector = self.saved

    def request(self, path, body=None):
        request = Request(self.root + path, data=None if body is None else json.dumps(body).encode(),
                          headers={'Content-Type': 'application/json'})
        try:
            response = urlopen(request, timeout=2)
        except HTTPError as exc:
            response = exc
        with response:
            return response.status, json.load(response)

    def test_health_preserves_model_scope(self):
        status, body = self.request('/health')
        self.assertEqual(status, 200)
        self.assertEqual(body['enabled_classes'], ['person'])
        self.assertFalse(body['open_vocabulary'])
        self.assertFalse(body['model_loaded'])

    def test_unsupported_class_does_not_load_model(self):
        with patch.object(api, 'Detector') as detector:
            status, body = self.request('/infer_image', {'image_base64': self.image, 'query': 'chair'})
        self.assertEqual(status, 422)
        self.assertEqual(body['error'], 'unsupported_class')
        detector.assert_not_called()

    def test_invalid_image_is_rejected(self):
        status, _ = self.request('/infer_image', {'image_base64': 'not_base64'})
        self.assertEqual(status, 400)
        self.assertIsNone(api.detector)

    def test_person_alias_response_and_unload(self):
        row = {'class': 'person', 'confidence': .9, 'bbox': [1, 2, 40, 60]}
        with patch.object(api, 'Detector') as detector:
            detector.return_value.infer.return_value = [row]
            status, body = self.request('/infer_image', {'image_base64': self.image, 'query': '人'})
            self.assertEqual(status, 200)
            self.assertEqual(body['detections'], [row])
            detector.assert_called_once_with()
            status, _ = self.request('/model/unload', {})
            self.assertEqual(status, 200)
            self.assertIsNone(api.detector)
