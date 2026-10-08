"""Read-only comparison of full left-camera FOV and rectified depth alignment."""
import io
import json
import sys
import urllib.request

import cv2
import numpy as np

from stereo_depth import StereoDepth


cal = json.load(open(sys.argv[1], encoding='utf-8'))
engine = StereoDepth(sys.argv[1])
with urllib.request.urlopen('http://127.0.0.1:8091/api/stereo/pair', timeout=5) as response:
    raw = response.read()
with np.load(io.BytesIO(raw), allow_pickle=False) as packet:
    left = cv2.imdecode(packet['left_jpeg'], cv2.IMREAD_COLOR)
    right = cv2.imdecode(packet['right_jpeg'], cv2.IMREAD_COLOR)
rect_rgb, _, rect_depth = engine.process(left, right)
xs, ys = np.meshgrid(np.arange(640, dtype=np.float32) * 2,
                     np.arange(360, dtype=np.float32) * 2)
points = np.stack((xs, ys), axis=-1).reshape(-1, 1, 2)
rectified = cv2.undistortPoints(points, np.array(cal['left_k']),
    np.array(cal['left_dist']), R=np.array(cal['rect_l']),
    P=np.array(cal['proj_l'])).reshape(360, 640, 2)
map_x = (rectified[:, :, 0] / 2).astype(np.float32)
map_y = (rectified[:, :, 1] / 2).astype(np.float32)
raw_depth = cv2.remap(rect_depth[60:420], map_x, map_y, cv2.INTER_NEAREST,
                      borderMode=cv2.BORDER_CONSTANT, borderValue=0)
in_bounds = (map_x >= 0) & (map_x < 640) & (map_y >= 0) & (map_y < 360)
rect_only = np.array(cal['proj_l'])[0, 0]
raw_fx = np.array(cal['left_k'])[0, 0]
print(json.dumps(dict(raw_shape=left.shape, rectified_focal_px=rect_only,
    raw_focal_px=raw_fx, horizontal_fov_raw_deg=float(2*np.degrees(np.arctan(640/raw_fx))),
    horizontal_fov_rect_deg=float(2*np.degrees(np.arctan(640/rect_only))),
    depth_valid_rect=float(np.mean(rect_depth[60:420] > 0)),
    depth_valid_raw=float(np.mean(raw_depth > 0)),
    raw_pixels_inside_rectified_domain=float(np.mean(in_bounds)),
    raw_depth_center_m=float(np.median(raw_depth[150:210, 260:380][raw_depth[150:210, 260:380] > 0]))/1000
        if np.any(raw_depth[150:210, 260:380] > 0) else None), indent=2))
