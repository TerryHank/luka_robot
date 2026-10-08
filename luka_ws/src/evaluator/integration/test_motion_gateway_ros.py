"""ROS transport check on a separate domain; no base/driver or sensor process."""
import json
import sys
import threading
import time
from pathlib import Path
import pytest

rclpy=pytest.importorskip('rclpy')
from rclpy.node import Node
from rclpy.executors import MultiThreadedExecutor
from geometry_msgs.msg import Twist
from sensor_msgs.msg import Joy
from std_msgs.msg import String

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'control/luka_motion_gateway'))
from luka_motion_gateway.node import MotionGateway
from luka_motion_gateway.client import MotionLeaseClient


def until(predicate,seconds=3.):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        if predicate():return
        time.sleep(.02)
    assert predicate(),'ROS state did not arrive before deadline'


def test_real_ros_lease_control_stop_manual_takeover_and_base_timeout():
    import os
    assert os.environ.get('ROS_DOMAIN_ID')=='187','Use isolated ROS_DOMAIN_ID=187'
    rclpy.init();gateway=MotionGateway();probe=Node('motion_gateway_transport_probe')
    lease=MotionLeaseClient(probe);received=[];revoked=[];lease.on_revoked=revoked.append
    pub=probe.create_publisher(Twist,'/luka/motion/nav',1)
    manual=probe.create_publisher(Joy,'/joy',10)
    base=probe.create_publisher(String,'/luka/base/status',10)
    health_timer=probe.create_timer(.05,lambda:base.publish(String(data=json.dumps({'healthy':True,'manual_active':False}))))
    probe.create_subscription(Twist,'/luka/motion/autonomy',lambda msg:received.append(msg.linear.x),10)
    executor=MultiThreadedExecutor(num_threads=3);executor.add_node(gateway);executor.add_node(probe)
    worker=threading.Thread(target=executor.spin,daemon=True);worker.start()
    try:
        until(lambda:lease.status and gateway.base_ready());lease.acquire('nav')
        command=Twist();command.linear.x=.1;pub.publish(command)
        until(lambda:received and received[-1]==.1)
        lease.stop();until(lambda:received[-1]==0.)
        until(lambda:lease.status.get('active_source') is None);lease.acquire('nav');pub.publish(command)
        until(lambda:received[-1]==.1)
        joy=Joy();joy.buttons=[0,0,0,0,1];manual.publish(joy)
        until(lambda:received[-1]==0. and lease.desired is None)
        assert 'nav' in revoked
        with pytest.raises(ValueError):lease.acquire('nav')
        joy.buttons=[0]*5;manual.publish(joy)
        until(lambda:not lease.status.get('manual_sources'));lease.acquire('nav');pub.publish(command)
        until(lambda:received[-1]==.1)
        probe.destroy_timer(health_timer)
        until(lambda:received[-1]==0. and lease.desired is None)
        assert len(revoked)>=2
    finally:
        lease.stop();executor.shutdown();worker.join(timeout=3)
        probe.destroy_node();gateway.destroy_node();rclpy.try_shutdown()
