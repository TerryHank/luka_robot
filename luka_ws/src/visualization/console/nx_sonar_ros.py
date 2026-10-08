#!/usr/bin/python3
"""CS100A ROS bridge. No motor commands. Nav inputs require all four fresh echoes."""
import json,math,time,os,socket
from pathlib import Path
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Range
from geometry_msgs.msg import TransformStamped
from tf2_ros.static_transform_broadcaster import StaticTransformBroadcaster
CONFIG=[('front_left',[7,15],.20,.09,.06,0),('front_right',[29,31],.20,-.09,.06,0),('left',[32,33],.20,.19,.15,math.pi/2),('right',[13,16],.20,-.19,.15,-math.pi/2)]
NAV_MAX=.8001

def valid(row,now):
 try:return row['status']=='echo' and 0<=now-row['sample_at']<.8 and math.isfinite(row['distance_m']) and .02<=row['distance_m']<=5
 except (KeyError,TypeError,ValueError):return False

def nav_range(distance):return distance if distance<=.8 else NAV_MAX

class Bridge(Node):
 def __init__(self):
  super().__init__('nx_sonar_ros');self.tf=StaticTransformBroadcaster(self);self.raw={};self.nav={};self.sent={};self.last_state=None
  transforms=[]
  for name,pins,x,y,z,yaw in CONFIG:
   self.raw[name]=self.create_publisher(Range,'/sonar/'+name,qos_profile_sensor_data)
   self.nav[name]=self.create_publisher(Range,'/sonar/nav/'+name,qos_profile_sensor_data)
   t=TransformStamped();t.header.stamp=self.get_clock().now().to_msg();t.header.frame_id='base_link';t.child_frame_id='sonar_'+name;t.transform.translation.x=x;t.transform.translation.y=y;t.transform.translation.z=z;t.transform.rotation.z=math.sin(yaw/2);t.transform.rotation.w=math.cos(yaw/2);transforms.append(t)
  self.tf.sendTransform(transforms);self.create_timer(.05,self.tick)
 def tick(self):
  try:
   data=json.loads(Path('/run/nx-sonar/status.json').read_text());now=time.time()
   rows={tuple(r['pins']):r for r in data['channels']}
   ready=0<=now-data['updated_at']<.8 and all(valid(rows.get(tuple(c[1]),{}),now) for c in CONFIG)
   reason='ready' if ready else 'No complete fresh four-channel data; navigation range stream paused'
   if reason!=self.last_state:self.get_logger().info(reason);self.last_state=reason
   for name,pins,*_ in CONFIG:
    row=rows.get(tuple(pins),{})
    if not valid(row,now):continue
    key=(name,'raw');stamp=row['sample_at']
    msg=Range();msg.header.frame_id='sonar_'+name;msg.header.stamp.sec=int(stamp);msg.header.stamp.nanosec=int((stamp-int(stamp))*1e9);msg.radiation_type=Range.ULTRASOUND;msg.field_of_view=math.radians(60);msg.min_range=.02;msg.max_range=5.;msg.range=float(row['distance_m'])
    if self.sent.get(key)!=stamp:self.raw[name].publish(msg);self.sent[key]=stamp
    if ready and self.sent.get((name,'nav'))!=stamp:
     msg.max_range=NAV_MAX;msg.range=nav_range(msg.range);self.nav[name].publish(msg);self.sent[(name,'nav')]=stamp
   report={'updated_at':now,'nav_inputs_ready':ready,'range_topics':[ '/sonar/nav/'+c[0] for c in CONFIG],'cutoff_m':.8,'note':'Range inputs only; no manual motor control'}
   p=Path('/run/nx-sonar-ros/status.json');tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(report));tmp.replace(p)
  except (OSError,ValueError,KeyError,TypeError) as e:
   if self.last_state!='error':self.get_logger().error('Sonar input unavailable: '+type(e).__name__);self.last_state='error'

def main():
 rclpy.init();node=Bridge()
 try:rclpy.spin(node)
 except KeyboardInterrupt:pass
 finally:node.destroy_node();rclpy.try_shutdown()
if __name__=='__main__':main()
