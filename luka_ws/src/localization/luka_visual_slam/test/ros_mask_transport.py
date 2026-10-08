"""Synthetic mask contract test in an isolated ROS domain, without hardware."""
import importlib.util
import json
import os
from pathlib import Path
import time
import numpy as np
os.environ['ROS_DOMAIN_ID']='189'
import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image,CameraInfo
from cv_bridge import CvBridge

path=Path(__file__).resolve().parents[1]/'scripts/depth_filter.py'
spec=importlib.util.spec_from_file_location('depth_filter_under_test',path)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
rclpy.init();node=module.DepthFilter();probe=rclpy.create_node('mask_contract_probe')
executor=SingleThreadedExecutor();executor.add_node(node);executor.add_node(probe)
bridge=CvBridge();received=[]
pubs={topic:probe.create_publisher(kind,topic,qos_profile_sensor_data)
      for topic,kind in (('rgb',Image),('depth',Image),('camera_info',CameraInfo),('dynamic_mask',Image))}
probe.create_subscription(Image,'filtered/depth',lambda m:received.append(bridge.imgmsg_to_cv2(m)),10)
def phase(age=0.,wrong_frame=False,with_mask=True):
    start=len(received);end=time.monotonic()+2.5
    while time.monotonic()<end:
        stamp=probe.get_clock().now().to_msg();stamp.sec-=int(age)
        rgb=bridge.cv2_to_imgmsg(np.zeros((2,2,3),np.uint8),encoding='rgb8')
        depth=bridge.cv2_to_imgmsg(np.array([[1000,2000],[3000,4000]],np.uint16),encoding='16UC1')
        mask=bridge.cv2_to_imgmsg(np.array([[0,255],[0,255]],np.uint8),encoding='mono8')
        info=CameraInfo();info.width=info.height=2;info.k=[1.,0.,1.,0.,1.,1.,0.,0.,1.]
        for m in (rgb,depth,mask,info):m.header.stamp=stamp;m.header.frame_id='optical'
        if wrong_frame:mask.header.frame_id='other'
        for key,m in (('rgb',rgb),('depth',depth),('camera_info',info)):pubs[key].publish(m)
        if with_mask:pubs['dynamic_mask'].publish(mask)
        for _ in range(15):executor.spin_once(timeout_sec=.01)
    return len(received)-start
try:
    good=phase();assert good>0
    assert all(x.tolist()==[[1000,0],[3000,0]] for x in received)
    stale=phase(age=2.);bad_frame=phase(wrong_frame=True);missing=phase(with_mask=False)
    assert stale==bad_frame==missing==0,(stale,bad_frame,missing)
    result={'pass':True,'valid_outputs':good,'stale_outputs':stale,'wrong_frame_outputs':bad_frame,'missing_mask_outputs':missing,'ros_domain':189}
    folder=Path('/home/sunrise/luka_ws/log/visual_slam');folder.mkdir(parents=True,exist_ok=True)
    (folder/'mask_transport.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
finally:
    executor.shutdown();node.destroy_node();probe.destroy_node();rclpy.shutdown()
