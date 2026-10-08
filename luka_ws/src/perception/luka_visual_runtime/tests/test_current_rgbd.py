from collections import deque
from types import SimpleNamespace as NS
import threading
import time

import numpy as np
from orbbec_ros_camera import OrbbecRosCamera


def camera_fixture():
    camera = OrbbecRosCamera.__new__(OrbbecRosCamera)
    stamp = time.time() - .01
    header = NS(stamp=NS(sec=int(stamp), nanosec=int((stamp % 1)*1e9)), frame_id='camera_color_optical_frame')
    camera.color_buffer = deque([(stamp, NS(header=header), np.zeros((480,640,3), np.uint8))], maxlen=10)
    camera.depth_buffer = deque([(stamp, NS(header=header, encoding='16UC1'), np.full((480,640),1500,np.uint16))], maxlen=10)
    camera.info = NS(header=header,width=640,height=480,k=[580.,0,320.,0,580.,240.,0,0,1.],d=[0.]*5)
    camera.latest = camera.latest_high = None
    camera.last_used_color_stamp = camera.last_used_depth_stamp = camera.last_match_mono = None
    camera.max_rgbd_dt = .12
    camera.latest_lock = threading.Lock()
    camera.calibration = {}
    camera.has_metric_depth = False
    camera.error = None
    return camera


def test_registered_factory_depth_is_available():
    camera = camera_fixture()
    camera._try_match_rgbd()
    assert camera.has_metric_depth
    assert camera.latest[3][200,200] == 1500
    assert camera.calibration['color'] == [580.,580.,320.,240.]


def test_unregistered_depth_is_rejected():
    camera = camera_fixture()
    camera.depth_buffer[0][1].header = NS(frame_id='camera_depth_optical_frame')
    camera._try_match_rgbd()
    assert not camera.has_metric_depth
    assert camera.latest is None


def test_stale_frame_is_rejected():
    camera = camera_fixture()
    color_stamp,msg,rgb = camera.color_buffer[0]
    depth_stamp,depth_msg,depth = camera.depth_buffer[0]
    camera.color_buffer[0] = (color_stamp-3,msg,rgb)
    camera.depth_buffer[0] = (depth_stamp-3,depth_msg,depth)
    camera._try_match_rgbd()
    assert not camera.has_metric_depth
    assert camera.latest is None


def test_unsynchronized_frames_are_rejected():
    camera = camera_fixture()
    stamp,msg,depth = camera.depth_buffer[0]
    camera.depth_buffer[0] = (stamp-.3,msg,depth)
    camera._try_match_rgbd()
    assert camera.latest is None
    assert camera.depth_reason == 'rgbd_sync_timeout'
