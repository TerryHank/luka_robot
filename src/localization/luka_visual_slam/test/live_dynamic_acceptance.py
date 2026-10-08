"""Observe real RGB-D/mask/filter output without issuing robot commands."""
from collections import OrderedDict
from pathlib import Path
import json
import time
import cv2
import numpy as np
import rclpy
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image
from std_msgs.msg import String
from cv_bridge import CvBridge

rclpy.init();node=rclpy.create_node('real_dynamic_mask_acceptance');bridge=CvBridge()
depths=OrderedDict();masks=OrderedDict();rgbs=OrderedDict()
result={'mask_frames':0,'nonzero_mask_frames':0,'filtered_frames':0,
        'verified_frames':0,'verified_person_frames':0,'removed_valid_depth_pixels':0,
        'pixel_mismatch_frames':0,'unpaired_frames':0,'max_mask_age_s':0.,'started':time.time()}
folder=Path('/home/sunrise/luka_data/recordings/visual_slam')/str(time.time_ns());folder.mkdir(parents=True)
def stamp(msg):return msg.header.stamp.sec+msg.header.stamp.nanosec*1e-9
def cache(target,msg):
    target[stamp(msg)]=msg
    while len(target)>40:target.popitem(last=False)
def mask(msg):
    cache(masks,msg);result['mask_frames']+=1
    result['nonzero_mask_frames']+=int(any(msg.data))
    result['max_mask_age_s']=max(result['max_mask_age_s'],time.time()-stamp(msg))
def filtered(msg):
    result['filtered_frames']+=1
    raw=depths.get(stamp(msg));candidates=[m for s,m in masks.items() if abs(s-stamp(msg))<=.06]
    if raw is None or not candidates:
        result['unpaired_frames']+=1;return
    before=bridge.imgmsg_to_cv2(raw);after=bridge.imgmsg_to_cv2(msg)
    matched=None
    for candidate in candidates:
        pixels=bridge.imgmsg_to_cv2(candidate)!=0
        expected=before.copy();expected[pixels]=0
        if np.array_equal(after,expected):matched=(candidate,pixels);break
    if matched is None:result['pixel_mismatch_frames']+=1;return
    result['verified_frames']+=1
    candidate,pixels=matched
    removed=int(np.count_nonzero((before>0)&pixels))
    result['verified_person_frames']+=int(removed>0)
    result['removed_valid_depth_pixels']+=removed
    if removed and not result.get('snapshot') and stamp(candidate) in rgbs:
        rgb=bridge.imgmsg_to_cv2(rgbs[stamp(candidate)],desired_encoding='bgr8')
        overlay=rgb.copy();overlay[pixels]=(0,0,255)
        overlay=cv2.addWeighted(rgb,.65,overlay,.35,0.)
        cv2.imwrite(str(folder/'rgb.png'),rgb);cv2.imwrite(str(folder/'mask.png'),pixels.astype(np.uint8)*255)
        cv2.imwrite(str(folder/'overlay.png'),overlay)
        np.save(folder/'depth_before.npy',before);np.save(folder/'depth_after.npy',after)
        result['snapshot']=str(folder);result['snapshot_removed_pixels']=removed

for topic,callback in [('/camera/color/image_raw',lambda m:cache(rgbs,m)),
                       ('/camera/depth/image_raw',lambda m:cache(depths,m)),
                       ('/perception/dynamic_mask',mask),
                       ('/rtabmap_rgbd/filtered/depth',filtered)]:
    node.create_subscription(Image,topic,callback,qos_profile_sensor_data)
node.create_subscription(String,'/perception/dynamic_mask/status',lambda m:result.update(inference_status=json.loads(m.data)),10)
print('LIVE_PERSON_TEST_READY',flush=True)
end=time.monotonic()+120;next_report=time.monotonic()+15
while time.monotonic()<end:
    rclpy.spin_once(node,timeout_sec=.1)
    if time.monotonic()>next_report:
        print(json.dumps(result),flush=True);next_report+=15
        (folder/'result.json').write_text(json.dumps(result,indent=2))
result['pass_real_mask_filter']=(result['verified_person_frames']>=10 and result['pixel_mismatch_frames']==0 and result.get('snapshot') is not None)
result['moving_loop_closure']='deferred: user can only keep camera stationary'
result['relocalization']='not tested in this stationary segmentation session'
(folder/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)
node.destroy_node();rclpy.shutdown()
