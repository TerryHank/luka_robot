"""Bounded read-only acceptance probe; never sends a navigation or motion command."""
import json
import math
from pathlib import Path
import time
import rclpy
from rclpy.qos import qos_profile_sensor_data
from nav_msgs.msg import Odometry, OccupancyGrid
from sensor_msgs.msg import PointCloud2
from rtabmap_msgs.msg import MapData
from tf2_msgs.msg import TFMessage

rclpy.init()
node = rclpy.create_node('rtabmap_rgbd_acceptance')
result = {'started': time.time(), 'odom_count': 0, 'finite_odom_count': 0,
          'map_nodes': 0, 'cloud_points': 0, 'map_cells': 0,
          'experimental_tf_messages': 0, 'private_tf_messages': 0, 'max_odom_age_s': 0.0}

def odom(msg):
    result['odom_count'] += 1
    p, q = msg.pose.pose.position, msg.pose.pose.orientation
    if all(math.isfinite(v) for v in (p.x, p.y, p.z, q.x, q.y, q.z, q.w)):
        result['finite_odom_count'] += 1
    result['odom_frame'] = msg.header.frame_id
    result['odom_child'] = msg.child_frame_id
    stamp = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
    result['max_odom_age_s'] = max(result['max_odom_age_s'], time.time()-stamp)

def map_data(msg):
    result['map_nodes'] = max(result['map_nodes'], len(msg.graph.poses_id))

def cloud(msg):
    result['cloud_points'] = max(result['cloud_points'], msg.width*msg.height)
    result['cloud_frame'] = msg.header.frame_id

def grid(msg):
    result['map_cells'] = max(result['map_cells'], msg.info.width*msg.info.height)

def tf(msg):
    result['experimental_tf_messages'] += sum(
        'rtabmap_rgbd' in t.header.frame_id or 'rtabmap_rgbd' in t.child_frame_id
        for t in msg.transforms)

def private_tf(msg):
    result['private_tf_messages'] += len(msg.transforms)

for topic,kind,callback in [('/rtabmap_rgbd/odom',Odometry,odom),
                           ('/rtabmap_rgbd/mapData',MapData,map_data),
                           ('/rtabmap_rgbd/cloud_map',PointCloud2,cloud),
                           ('/rtabmap_rgbd/map',OccupancyGrid,grid),
                           ('/tf',TFMessage,tf),
                           ('/rtabmap_rgbd/tf',TFMessage,private_tf)]:
    node.create_subscription(kind,topic,callback,qos_profile_sensor_data)
print('OBSERVING_30_SECONDS',flush=True)
deadline = time.monotonic()+30
while time.monotonic()<deadline:
    rclpy.spin_once(node,timeout_sec=.1)
result['production_publishers'] = {
    topic:[p.node_namespace+'/'+p.node_name for p in node.get_publishers_info_by_topic(topic)]
    for topic in ('/map','/odom','/cmd_vel')}
result['pass_stationary_initialization'] = (
    result['odom_count']>=10 and result['finite_odom_count']==result['odom_count']
    and result['map_nodes']>0 and result['cloud_points']>0
    and result['experimental_tf_messages']==0 and result['private_tf_messages']>0
    and not any('rtabmap_rgbd' in p for values in result['production_publishers'].values() for p in values))
result['moving_mapping_and_loop_closure'] = 'not tested'
folder = Path('/home/sunrise/luka_ws/log/rtabmap_rgbd')
folder.mkdir(parents=True,exist_ok=True)
(folder/'acceptance.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result),flush=True)
node.destroy_node()
rclpy.shutdown()
