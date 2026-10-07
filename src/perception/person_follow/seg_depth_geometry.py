"""Trimmed mean of registered metric depth inside a cropped person mask."""
import math
import cv2
import numpy as np


DEFAULT_TRIM_RATIO = 0.15


def seg_mean_geometry(depth, bbox, person_mask, intrinsics, skew_s, trim_ratio=DEFAULT_TRIM_RATIO, min_depth_m=0.3, max_depth_m=6.0):
    invalid = {'valid': False, 'source': 'orbbec_registered_seg_trimmed_mean'}
    if depth is None or person_mask is None:
        return dict(invalid, reason='missing_seg_depth')
    if not np.isfinite(skew_s) or abs(skew_s) > .05:
        return dict(invalid, reason='rgb_depth_not_synchronized')
    if not np.isfinite(trim_ratio) or not 0 <= trim_ratio < .5:
        return dict(invalid, reason='invalid_trim_ratio')
    if (not np.isfinite(min_depth_m) or not np.isfinite(max_depth_m) or
            min_depth_m <= 0 or max_depth_m <= min_depth_m):
        return dict(invalid, reason='invalid_depth_range')
    x1,y1,x2,y2 = map(int,bbox)
    if depth.ndim != 2 or not (0 <= x1 < x2 <= depth.shape[1] and 0 <= y1 < y2 <= depth.shape[0]):
        return dict(invalid, reason='invalid_bbox')
    mask = np.asarray(person_mask,dtype=bool)
    if mask.shape != (y2-y1,x2-x1):
        return dict(invalid, reason='mask_depth_shape_mismatch')
    crop = depth[y1:y2,x1:x2]
    valid = mask & np.isfinite(crop) & (crop >= min_depth_m) & (crop <= max_depth_m)
    mask_pixels = int(np.count_nonzero(mask))
    count = int(np.count_nonzero(valid))
    if count < 30 or count < .1*mask_pixels:
        return dict(invalid, reason='insufficient_valid_seg_depth')
    if intrinsics is None or any(not math.isfinite(intrinsics[key]) for key in ('fx','fy','cx','cy')) or min(intrinsics['fx'],intrinsics['fy']) <= 0:
        return dict(invalid, reason='invalid_intrinsics')
    values = np.sort(crop[valid].astype(np.float64))
    trim_count = int(len(values) * trim_ratio)
    trimmed = values[trim_count:len(values)-trim_count] if trim_count else values
    if not len(trimmed):
        return dict(invalid, reason='insufficient_trimmed_seg_depth')
    mean_m = float(np.mean(trimmed))
    raw_mean_m = float(np.mean(values))
    ys,xs = np.nonzero(valid)
    u,v = float(xs.mean()+x1),float(ys.mean()+y1)
    fx,fy,cx,cy = (intrinsics[key] for key in ('fx','fy','cx','cy'))
    ray = np.array([(u-cx)/fx,(v-cy)/fy])
    distortion = intrinsics.get('distortion')
    if distortion is not None:
        camera_matrix = np.array([[fx,0,cx],[0,fy,cy],[0,0,1]],dtype=np.float64)
        ray = cv2.undistortPoints(np.array([[[u,v]]],dtype=np.float64),camera_matrix,
                                 np.asarray(distortion,dtype=np.float64)).reshape(2)
    optical = [float(ray[0]*mean_m),float(ray[1]*mean_m),mean_m]
    diagnostic = {'method':'seg_valid_trimmed_mean','mask_pixels':mask_pixels,
        'valid_pixels':count,'valid_fraction':count/mask_pixels,
        'trim_ratio':float(trim_ratio),'trimmed_pixels':int(len(trimmed)),
        'min_depth_m':float(min_depth_m),'max_depth_m':float(max_depth_m),
        'depth_raw_mean_m':raw_mean_m,'depth_std_m':float(np.std(values)),
        'depth_trimmed_min_m':float(trimmed[0]),'depth_trimmed_max_m':float(trimmed[-1]),
        'centroid_uv':[u,v],'position_optical_m':optical,
        'width_m':(x2-x1)*mean_m/fx,'height_m':(y2-y1)*mean_m/fy,
        'rgb_depth_skew_s':float(skew_s)}
    return {'valid':True,'reason':'seg_trimmed_mean_valid',
            'source':'orbbec_registered_seg_trimmed_mean',
            'distance_m':mean_m,'bearing_rad':math.atan2(optical[0],mean_m),
            'diagnostic':diagnostic}
