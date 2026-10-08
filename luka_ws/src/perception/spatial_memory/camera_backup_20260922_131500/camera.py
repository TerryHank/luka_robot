"""Fixed Orbbec Astra RGB-D camera, factory calibration and native D2C."""
import ctypes
import threading
import time
import cv2
import numpy as np
from openni import openni2


class Calibration(ctypes.Structure):
    _fields_ = [(key,ctypes.c_float*size) for key,size in
                [('depth',4),('color',4),('rotation',9),('translation',3),
                 ('depth_dist',5),('color_dist',5)]]


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


class Camera:
    def __init__(self, sdk, device=0):
        self.latest = None
        self.error = None
        self.stopping = False
        openni2.initialize(str(sdk))
        self.device = openni2.Device.open_any()
        params = self.device.get_property(14,Calibration)
        self.calibration = {key:list(getattr(params,key)) for key,_ in params._fields_}
        if not all(np.isfinite(self.calibration['color'])) or min(self.calibration['color'][:2])<100:
            raise RuntimeError('Invalid factory RGB calibration')
        self.depth = self.device.create_depth_stream()
        self.depth.configure_mode(640,480,30,openni2.PIXEL_FORMAT_DEPTH_1_MM)
        self.depth.set_mirroring_enabled(False)
        mode = openni2.IMAGE_REGISTRATION_DEPTH_TO_COLOR
        if not self.device.is_image_registration_mode_supported(mode):
            raise RuntimeError('Depth-to-color registration is required')
        self.device.set_image_registration_mode(mode)
        self.depth.start()
        self.color = cv2.VideoCapture(device,cv2.CAP_V4L2)
        self.color.set(cv2.CAP_PROP_FRAME_WIDTH,640)
        self.color.set(cv2.CAP_PROP_FRAME_HEIGHT,480)
        self.color.set(cv2.CAP_PROP_BUFFERSIZE,1)
        if not self.color.isOpened():
            raise RuntimeError('RGB camera could not be opened')
        self.thread = threading.Thread(target=self._capture,daemon=True)
        self.thread.start()

    def _capture(self):
        try:
            for _ in range(10):
                self.color.read()
            while not self.stopping:
                openni2.wait_for_any_stream([self.depth],2000)
                frame = self.depth.read_frame()
                depth_time = time.monotonic()
                depth = np.array(frame.get_buffer_as_uint16()).reshape(frame.height,frame.width)
                ok, rgb = self.color.read()
                if not ok or rgb.shape[:2]!=(480,640):
                    raise RuntimeError('RGB frame missing or unexpected size')
                # UVC and OpenNI have separate clocks; this is approximate host pairing.
                skew = time.monotonic()-depth_time
                self.latest = (time.time(),time.monotonic(),rgb,depth,skew)
        except Exception as exc:
            self.error = repr(exc)

    def close(self):
        self.stopping = True
        self.thread.join(timeout=3)
        if not self.thread.is_alive():
            self.color.release()
            self.depth.stop()
            self.device.close()
            openni2.unload()
