"""Evaluate the existing localization policy with real sensors; never commands wheels."""
import argparse
import json
import math
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
for path in ('visualization/console','behavior/luka_behaviors'):
    sys.path.insert(0,str(ROOT/path))
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import LaserScan
from geometry_msgs.msg import PoseWithCovarianceStamped
from object_pose_context import ObjectPoseContext
from luka_behaviors.relocalization import Relocalization
from nx_product_api import ProductAPI
from s100_boot_pose import load_saved_pose,navigation_verified


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--initialize-saved',action='store_true')
    args=parser.parse_args();rclpy.init();node=Node('luka_architecture_static_pose_audit')
    node.workspace=Path('/home/sunrise/luka_ws');node.current_floor_id='floor_4';node.selected_map='floor_4'
    node.pose=None;node.last={'scan':0.,'pose':0.}
    node.object_pose_context=ObjectPoseContext(node)
    node.relocalization=Relocalization(node,lambda:None)
    def scan(_):node.last['scan']=time.monotonic()
    node.create_subscription(LaserScan,'/scan',scan,qos_profile_sensor_data)
    product=ProductAPI.__new__(ProductAPI);product.node=node
    began=time.monotonic();seeded=False;update_at=0.;result={}
    try:
        while time.monotonic()-began<25:
            rclpy.spin_once(node,timeout_sec=.1)
            if args.initialize_saved and not seeded and node.relocalization.pub.get_subscription_count():
                pose=load_saved_pose()
                if pose is None:raise ValueError('No saved pose matches the active map signature')
                msg=PoseWithCovarianceStamped();msg.header.frame_id='map';msg.header.stamp=node.get_clock().now().to_msg()
                msg.pose.pose.position.x=pose['x'];msg.pose.pose.position.y=pose['y']
                msg.pose.pose.orientation.z=math.sin(pose['yaw']/2);msg.pose.pose.orientation.w=math.cos(pose['yaw']/2)
                msg.pose.covariance[0]=msg.pose.covariance[7]=.25;msg.pose.covariance[35]=math.radians(25)**2
                node.relocalization.pub.publish(msg);seeded=True
            if time.monotonic()-update_at>1 and node.relocalization.update_client.service_is_ready():
                from std_srvs.srv import Empty
                node.relocalization.update_client.call_async(Empty.Request());update_at=time.monotonic()
            result=product.localization_status()
            if navigation_verified(result):break
        print(json.dumps({'seeded':seeded,'navigation_verified':navigation_verified(result),
                          'status':result},ensure_ascii=False,allow_nan=False))
        return 0 if navigation_verified(result) else 2
    finally:node.destroy_node();rclpy.try_shutdown()


if __name__=='__main__':raise SystemExit(main())
