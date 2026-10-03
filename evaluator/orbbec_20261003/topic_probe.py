import json, time
from pathlib import Path
import numpy as np
import rclpy
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image, CameraInfo

rclpy.init()
node=rclpy.create_node('luka_orbbec_topic_acceptance')
stats={}
def receive(topic,msg):
    now=time.monotonic()
    entry=stats.setdefault(topic,{'messages':0,'first':now})
    entry.update(messages=entry['messages']+1,last=now,frame_id=msg.header.frame_id,
        width=msg.width,height=msg.height)
    entry['age_seconds']=time.time()-msg.header.stamp.sec-msg.header.stamp.nanosec/1e9
    if isinstance(msg,Image):
        entry['encoding']=msg.encoding
        if msg.encoding=='16UC1':
            depth=np.ndarray((msg.height,msg.width),dtype='>u2' if msg.is_bigendian else '<u2',buffer=msg.data,strides=(msg.step,2))
            valid=depth[(depth>0)&(depth<8000)]
            entry['valid_fraction']=len(valid)/depth.size
            entry['median_depth_m']=float(np.median(valid))/1000 if len(valid) else None
    else:
        entry['k']=list(msg.k)
        entry['distortion']=list(msg.d)
subscriptions=[]
for stream in ('color','depth'):
    for suffix,kind in [('image_raw',Image),('camera_info',CameraInfo)]:
        topic=f'/camera/{stream}/{suffix}'
        subscriptions.append(node.create_subscription(kind,topic,lambda m,t=topic:receive(t,m),qos_profile_sensor_data))
deadline=time.monotonic()+15
while time.monotonic()<deadline:rclpy.spin_once(node,timeout_sec=.1)
for entry in stats.values():
    elapsed=entry.pop('last')-entry.pop('first')
    entry['hz']=(entry['messages']-1)/elapsed if elapsed else 0
Path('/home/sunrise/luka_ws/evaluator/orbbec_20261003/topic_reception.json').write_text(json.dumps(stats,indent=2))
print(json.dumps(stats),flush=True)
node.destroy_node()
rclpy.shutdown()
