"""Bounded wheels-off-ground acceptance through NavigateBehavior and the real safety chain."""
import argparse
import json
import math
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[2]
for path in ('visualization/console','behavior/luka_behaviors','control/luka_motion_gateway'):
    sys.path.insert(0,str(ROOT/path))
import rclpy
from rclpy.node import Node
from rclpy.executors import MultiThreadedExecutor
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import LaserScan
from std_msgs.msg import String
from geometry_msgs.msg import Twist
from nav2_msgs.msg import SpeedLimit
from object_pose_context import ObjectPoseContext
from luka_behaviors.registry import BehaviorRegistry
from nx_product_api import ProductAPI
from s100_boot_pose import navigation_verified


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--wheels-off-ground',action='store_true',required=True)
    args=parser.parse_args();rclpy.init();node=Node('luka_architecture_navigation_wheels')
    node.workspace=Path('/home/sunrise/luka_ws');node.current_floor_id='floor_4';node.selected_map='floor_4'
    node.pose=None;node.last={'scan':0.,'pose':0.}
    node.object_pose_context=ObjectPoseContext(node)
    node.patrol_mission=SimpleNamespace(active=lambda:False)
    node.follow_controller=SimpleNamespace(enabled=False)
    node.behaviors=BehaviorRegistry(node,lambda:[],navigation_verified)
    node.relocalization=node.behaviors.relocalize.legacy_controller
    node.product=ProductAPI.__new__(ProductAPI);node.product.node=node
    def refresh_pose():
        from std_srvs.srv import Empty
        if node.nx_handle is None and node.relocalization.update_client.service_is_ready():
            node.relocalization.update_client.call_async(Empty.Request())
    node.create_timer(.5,refresh_pose)
    node.create_subscription(LaserScan,'/scan',lambda _:node.last.update(scan=time.monotonic()),qos_profile_sensor_data)
    samples=[];safe=[]
    node.create_subscription(String,'/ddsm/data_chain',lambda msg:samples.append(json.loads(msg.data)),10)
    node.create_subscription(Twist,'/nx/nav_safe',lambda msg:safe.append([msg.linear.x,msg.linear.y,msg.angular.z]),10)
    limit=node.create_publisher(SpeedLimit,'/speed_limit',10)
    executor=MultiThreadedExecutor(num_threads=3);executor.add_node(node)
    worker=threading.Thread(target=executor.spin,daemon=True);worker.start();accepted=False;before=[]
    try:
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            if samples and node.motion.status and navigation_verified(node.product.localization_status()):break
            time.sleep(.1)
        status=node.product.localization_status()
        if not navigation_verified(status):raise ValueError('Localization policy rejects movement: '+status['reason'])
        if not samples or any(not row['valid'] or row['age_s']>.5 for row in samples[-1]['motor_feedback_input']['wheels']):
            raise ValueError('Fresh four-wheel encoder feedback is required')
        before=[row['position_degrees'] for row in samples[-1]['motor_feedback_input']['wheels']]
        speed=SpeedLimit();speed.percentage=False;speed.speed_limit=.08;limit.publish(speed);time.sleep(.3)
        pose=status['pose'];target={'id':'architecture-wheels','display_name':'架空轮导航验收',
            'x':pose['x']+.3*math.cos(pose['yaw']),'y':pose['y']+.3*math.sin(pose['yaw']),'yaw':pose['yaw']}
        node.behaviors.navigate.start(None,observation=target);accepted=node.nx_handle is not None
        began=time.monotonic()
        while time.monotonic()-began<2:
            if not node.motion.valid('nav'):raise ValueError('Navigation motion lease was revoked')
            if samples[-1]['motor_feedback_input']['last_feedback_error']:raise ValueError('Encoder became invalid')
            if safe and (abs(safe[-1][0])>.12 or abs(safe[-1][1])>.12):raise ValueError('Low-speed envelope exceeded')
            if any(abs(row['position_degrees']-old)>.3 for row,old in zip(samples[-1]['motor_feedback_input']['wheels'],before)):break
            time.sleep(.05)
    finally:
        node.behaviors.navigate.cancel();node.motion.stop()
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            if samples and all(row['rpm']==0 for row in samples[-1]['bridge_rs485_output']['target_motor_rpm']):break
            time.sleep(.05)
        after=[row['position_degrees'] for row in samples[-1]['motor_feedback_input']['wheels']] if samples else []
        stopped=bool(samples and all(row['rpm']==0 for row in samples[-1]['bridge_rs485_output']['target_motor_rpm']))
        moved=bool(before and any(abs(new-old)>.3 for new,old in zip(after,before)))
        print(json.dumps({'action_accepted':accepted,'encoder_before':before,'encoder_after':after,
                          'encoder_movement_seen':moved,'stop_confirmed':stopped,'safe_samples':len(safe)},allow_nan=False))
        speed=SpeedLimit();speed.speed_limit=0.;speed.percentage=False;limit.publish(speed)
        executor.shutdown();worker.join(timeout=3);node.destroy_node();rclpy.try_shutdown()
    return 0 if accepted and moved and stopped else 2


if __name__=='__main__':raise SystemExit(main())
