"""Fixed Orbbec Astra RGB-D camera, factory calibration and native D2C."""
import ctypes
import os
from pathlib import Path
import threading
import time
import cv2
import numpy as np
try:
    from openni import openni2
except ImportError:
    openni2 = None


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


def _rgb_devices(preferred=None):
    """Return stable UVC colour paths before volatile /dev/video numbers."""
    candidates = []
    if preferred is not None:
        candidates.append(preferred if isinstance(preferred, str) else f'/dev/video{preferred}')
    candidates.extend(str(path) for path in sorted(Path('/dev/v4l/by-id').glob('*-video-index0')))
    candidates.extend(str(path) for path in sorted(Path('/dev').glob('video*'), key=lambda p: p.name))
    result = []
    for item in candidates:
        if item not in result:
            result.append(item)
    return result


class Camera:
    def __init__(self, sdk, device=None):
        if openni2 is None:
            raise RuntimeError('OpenNI is required only for the legacy Orbbec camera')
        self.latest = None
        self.latest_high = None
        self.latest_lock = threading.Lock()
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
        self.color, self.rgb_device = None, None
        self.rgb_width = int(os.getenv('NX_FACE_RGB_WIDTH', '1280'))
        self.rgb_height = int(os.getenv('NX_FACE_RGB_HEIGHT', '960'))
        if (self.rgb_width, self.rgb_height) not in ((640, 480), (1280, 960)):
            raise ValueError('Unsupported RGB capture size')
        attempted = []
        for candidate in _rgb_devices(device):
            attempted.append(str(candidate))
            capture = cv2.VideoCapture(candidate,cv2.CAP_V4L2)
            if self.rgb_width > 640:
                capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
            capture.set(cv2.CAP_PROP_FRAME_WIDTH,self.rgb_width)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT,self.rgb_height)
            capture.set(cv2.CAP_PROP_FPS,30)
            capture.set(cv2.CAP_PROP_BUFFERSIZE,1)
            if capture.isOpened():
                self.color, self.rgb_device = capture, str(candidate)
                break
            capture.release()
        if self.color is None:
            raise RuntimeError('RGB camera could not be opened; tried ' + ', '.join(attempted))
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
                ok, native_rgb = self.color.read()
                if not ok or native_rgb.shape[:2] != (self.rgb_height,self.rgb_width):
                    raise RuntimeError('RGB frame missing or unexpected size')
                rgb = (cv2.resize(native_rgb, (640, 480), interpolation=cv2.INTER_AREA)
                       if self.rgb_width > 640 else native_rgb)
                # UVC and OpenNI have separate clocks; this is approximate host pairing.
                skew = time.monotonic()-depth_time
                stamp, mono = time.time(), time.monotonic()
                with self.latest_lock:
                    self.latest_high = (mono, native_rgb) if self.rgb_width > 640 else None
                    self.latest = (stamp,mono,rgb,depth,skew)
        except Exception as exc:
            self.error = repr(exc)

    def people_snapshot(self):
        with self.latest_lock:
            return self.latest, self.latest_high

    def close(self):
        self.stopping = True
        self.thread.join(timeout=3)
        if not self.thread.is_alive():
            self.color.release()
            self.depth.stop()
            self.device.close()
            openni2.unload()
