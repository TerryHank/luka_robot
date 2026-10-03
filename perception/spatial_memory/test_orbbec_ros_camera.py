import threading
import time
from types import SimpleNamespace as NS

import numpy as np
from orbbec_ros_camera import OrbbecRosCamera


def camera_fixture():
    camera = OrbbecRosCamera.__new__(OrbbecRosCamera)
    stamp = time.time() - .01
    header = NS(stamp=NS(sec=int(stamp), nanosec=int((stamp % 1)*1e9)), frame_id='camera_color_optical_frame')
    camera.rgb = (NS(header=header), np.zeros((480,640,3), np.uint8))
    camera.depth = (NS(header=header), np.full((480,640),1500,np.uint16))
    camera.info = NS(header=header,width=640,height=480,k=[580.,0,320.,0,580.,240.,0,0,1.],d=[0.]*5)
    camera.latest = camera.latest_high = None
    camera.latest_lock = threading.Lock()
    camera.calibration = {}
    camera.has_metric_depth = False
    camera.error = None
    return camera


def test_registered_factory_depth_is_available():
    camera = camera_fixture()
    camera._publish()
    assert camera.has_metric_depth
    assert camera.latest[3][200,200] == 1500
    assert camera.calibration['color'] == [580.,580.,320.,240.]


def test_unregistered_depth_is_rejected():
    camera = camera_fixture()
    camera.depth = (NS(header=NS(stamp=camera.depth[0].header.stamp,frame_id='camera_depth_optical_frame')),camera.depth[1])
    camera._publish()
    assert not camera.has_metric_depth
    assert camera.latest is None


def test_stale_frame_is_rejected():
    camera = camera_fixture()
    camera.info.header.stamp.sec -= 3
    camera._publish()
    assert not camera.has_metric_depth
    assert camera.latest is None
