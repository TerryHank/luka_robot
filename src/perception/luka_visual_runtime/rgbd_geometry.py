"""Registered RGB-D surface geometry; no physical camera acquisition."""
import cv2
import numpy as np

def object_position(depth, bbox, intrinsic, distortion):
    """Robust central surface estimate; invalid depth is never a zero-distance hit."""
    x1,y1,x2,y2 = bbox
    cx,cy = (x1+x2)/2,(y1+y2)/2
    rx,ry = max(3,int((x2-x1)*.15)), max(3,int((y2-y1)*.15))
    patch = depth[max(0,int(cy)-ry):min(depth.shape[0],int(cy)+ry+1),
                  max(0,int(cx)-rx):min(depth.shape[1],int(cx)+rx+1)]
    values = patch[(patch>=300)&(patch<=8000)]
    fraction = len(values)/max(1,patch.size)
    if len(values)<12 or fraction<.25:
        return None, {'valid_fraction':round(fraction,3),'reason':'insufficient_depth'}
    z = float(np.median(values))/1000
    spread = float(np.percentile(values,75)-np.percentile(values,25))/1000
    if spread > max(.2,.15*z):
        return None, {'valid_fraction':round(fraction,3),'reason':'mixed_surfaces'}
    fx,fy,ox,oy = intrinsic
    matrix = np.array([[fx,0,ox],[0,fy,oy],[0,0,1]],np.float64)
    ray = cv2.undistortPoints(np.array([[[cx,cy]]],np.float64),matrix,np.array(distortion))[0,0]
    xyz = [round(float(ray[0]*z),3),round(float(ray[1]*z),3),round(z,3)]
    return xyz, {'valid_fraction':round(fraction,3),'depth_iqr_m':round(spread,3),'method':'bbox_center_median_surface'}
