"""Calibrated, read-only metric depth for a side-by-side UVC stereo camera."""
import json
import time
from pathlib import Path

import cv2
import numpy as np


def disparity_to_mm(disparity_half_px, focal_baseline_full_px_m):
    """Convert half-width rectified disparity to mm; invalid pixels stay zero."""
    disparity = np.asarray(disparity_half_px, dtype=np.float32)
    if disparity.ndim != 2:
        raise ValueError('disparity must be a 2-D image')
    focal_baseline = float(focal_baseline_full_px_m)
    if not np.isfinite(focal_baseline) or focal_baseline <= 0:
        raise ValueError('invalid rectified focal-baseline product')
    valid = np.isfinite(disparity) & (disparity > 2) & (disparity < 128)
    metres = np.zeros(disparity.shape, np.float32)
    np.divide(focal_baseline, 2 * disparity, out=metres, where=valid)
    valid &= (metres >= .3) & (metres <= 4.)
    result = np.zeros(disparity.shape, np.uint16)
    result[valid] = np.rint(metres[valid] * 1000).astype(np.uint16)
    return result


class StereoDepth:
    def __init__(self, calibration_path):
        cal = json.loads(Path(calibration_path).read_text(encoding='utf-8'))
        if (cal.get('image_size') != [1280, 720] or cal.get('pattern') != [9, 6] or
                cal.get('validated_known_distances') is not True or
                cal.get('enabled_for_robot') is not False):
            raise ValueError('calibration has not passed static metric validation')
        left_k = np.asarray(cal['left_k'], np.float64)
        right_k = np.asarray(cal['right_k'], np.float64)
        left_d = np.asarray(cal['left_dist'], np.float64)
        right_d = np.asarray(cal['right_dist'], np.float64)
        left_r = np.asarray(cal['rect_l'], np.float64)
        right_r = np.asarray(cal['rect_r'], np.float64)
        left_p = np.asarray(cal['proj_l'], np.float64)
        right_p = np.asarray(cal['proj_r'], np.float64)
        baseline = abs(float(right_p[0, 3] / right_p[0, 0]))
        if not .03 <= baseline <= .3 or not 300 <= left_p[0, 0] <= 3000:
            raise ValueError('implausible stereo baseline or focal length')
        self.focal_baseline = abs(float(right_p[0, 3]))
        self.intrinsic_640x480 = [float(left_p[0, 0]/2), float(left_p[1, 1]/2),
                                  float(left_p[0, 2]/2), float(left_p[1, 2]/2+60)]
        self.raw_intrinsic_640x480 = [float(left_k[0, 0]/2), float(left_k[1, 1]/2),
                                      float(left_k[0, 2]/2), float(left_k[1, 2]/2+60)]
        self.raw_distortion = left_d.reshape(-1).astype(float).tolist()
        # For a full-FOV *people-only* image, look up rectified depth along
        # each original left-camera ray. Areas outside the stereo overlap stay
        # zero/unknown; never extrapolate a distance to the image edges.
        raw_x, raw_y = np.meshgrid(np.arange(640, dtype=np.float32)*2,
                                    np.arange(360, dtype=np.float32)*2)
        raw_points = np.stack((raw_x, raw_y), axis=-1).reshape(-1, 1, 2)
        rect_points = cv2.undistortPoints(raw_points, left_k, left_d,
            R=left_r, P=left_p).reshape(360, 640, 2)
        self.raw_depth_map_x = np.ascontiguousarray(rect_points[:, :, 0]/2, dtype=np.float32)
        self.raw_depth_map_y = np.ascontiguousarray(rect_points[:, :, 1]/2, dtype=np.float32)
        self.last_raw_valid_fraction = None
        size = (1280, 720)
        self.left_map = cv2.initUndistortRectifyMap(left_k, left_d, left_r, left_p, size, cv2.CV_16SC2)
        self.right_map = cv2.initUndistortRectifyMap(right_k, right_d, right_r, right_p, size, cv2.CV_16SC2)
        block = 5
        self.matcher = cv2.StereoSGBM_create(minDisparity=0, numDisparities=128, blockSize=block,
            P1=8*block*block, P2=32*block*block, uniquenessRatio=8,
            speckleWindowSize=50, speckleRange=2, disp12MaxDiff=1)
        self.last_processing_s = None
        self.last_valid_fraction = None

    def process(self, left, right):
        if left.shape != (720, 1280, 3) or right.shape != left.shape:
            raise ValueError('expected two 1280x720 BGR frames')
        started = time.monotonic()
        rect_left = cv2.remap(left, *self.left_map, cv2.INTER_LINEAR)
        rect_right = cv2.remap(right, *self.right_map, cv2.INTER_LINEAR)
        small_left = cv2.resize(rect_left, (640, 360), interpolation=cv2.INTER_AREA)
        small_right = cv2.resize(rect_right, (640, 360), interpolation=cv2.INTER_AREA)
        gray_left = cv2.cvtColor(small_left, cv2.COLOR_BGR2GRAY)
        gray_right = cv2.cvtColor(small_right, cv2.COLOR_BGR2GRAY)
        disparity = self.matcher.compute(gray_left, gray_right).astype(np.float32) / 16.
        depth = disparity_to_mm(disparity, self.focal_baseline)
        self.last_valid_fraction = float(np.count_nonzero(depth) / depth.size)
        self.last_processing_s = time.monotonic() - started
        # Detection RGB is a padded version of the same rectified exposure.
        high = cv2.copyMakeBorder(rect_left, 120, 120, 0, 0, cv2.BORDER_CONSTANT,
                                   value=(0, 0, 0))
        rgb = cv2.resize(high, (640, 480), interpolation=cv2.INTER_AREA)
        depth_padded = np.pad(depth, ((60, 60), (0, 0)), mode='constant')
        return rgb, high, depth_padded

    def people_view(self, raw_left, rectified_depth_padded):
        """Preserve the left lens FOV while retaining only measured depth."""
        if raw_left.shape != (720, 1280, 3) or rectified_depth_padded.shape != (480, 640):
            raise ValueError('people view dimensions do not match calibration')
        depth_raw = cv2.remap(rectified_depth_padded[60:420],
            self.raw_depth_map_x, self.raw_depth_map_y, cv2.INTER_NEAREST,
            borderMode=cv2.BORDER_CONSTANT, borderValue=0)
        self.last_raw_valid_fraction = float(np.count_nonzero(depth_raw) / depth_raw.size)
        high = cv2.copyMakeBorder(raw_left, 120, 120, 0, 0,
                                  cv2.BORDER_CONSTANT, value=(0, 0, 0))
        rgb = cv2.resize(high, (640, 480), interpolation=cv2.INTER_AREA)
        return rgb, high, np.pad(depth_raw, ((60, 60), (0, 0)), mode='constant')
