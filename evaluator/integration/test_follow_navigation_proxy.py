"""Actual ROS action transport with a simulated Nav2 backend on domain 187."""
import json
import sys
import threading
import time
from pathlib import Path
import pytest

rclpy=pytest.importorskip('rclpy')
from rclpy.node import Node
from rclpy.executors import MultiThreadedExecutor
from rclpy.action import ActionServer,ActionClient
from nav2_msgs.action import NavigateToPose
from std_msgs.msg import String

ROOT=Path(__file__).resolve().parents[2]
for area in ('behavior/luka_behaviors','control/luka_motion_gateway'):sys.path.insert(0,str(ROOT/area))
from luka_motion_gateway.node import MotionGateway
from luka_motion_gateway.client import MotionLeaseClient
from luka_behaviors.follow_navigation import FollowNavigationProxy


def wait(predicate):
    end=time.monotonic()+4
    while time.monotonic()<end:
        if predicate():return
        time.sleep(.01)
    assert predicate(),'action/lease did not complete'


def test_follow_nav_proxy_switches_owned_lease_and_rejects_nonfinite_goal():
    import os
    assert os.environ.get('ROS_DOMAIN_ID')=='187'
    rclpy.init();gateway=MotionGateway();bridge=Node('follow_proxy_test_bridge');backend=Node('follow_proxy_test_nav2')
    lease=MotionLeaseClient(bridge);proxy=FollowNavigationProxy(bridge,lease,lambda:True)
    base=backend.create_publisher(String,'/luka/base/status',10)
    backend.create_timer(.05,lambda:base.publish(String(data=json.dumps({'healthy':True,'manual_active':False}))))
    received=[]
    def execute(goal):
        received.append(goal.request);goal.succeed();return NavigateToPose.Result()
    server=ActionServer(backend,NavigateToPose,'/navigate_to_pose',execute_callback=execute)
    client=ActionClient(backend,NavigateToPose,'/luka/behavior/follow_navigation')
    executor=MultiThreadedExecutor(num_threads=4)
    for node in (gateway,bridge,backend):executor.add_node(node)
    worker=threading.Thread(target=executor.spin,daemon=True);worker.start()
    try:
        wait(lambda:lease.status and gateway.base_ready() and proxy.client.server_is_ready() and client.server_is_ready())
        lease.acquire('follow');generation=lease.status['generation']
        goal=NavigateToPose.Goal();goal.pose.header.frame_id='map';goal.pose.pose.orientation.w=1.
        goal.pose.pose.position.x=float('nan')
        invalid=client.send_goal_async(goal);wait(invalid.done);assert not invalid.result().accepted
        goal.pose.pose.position.x=1.
        future=client.send_goal_async(goal);wait(future.done);handle=future.result();assert handle.accepted
        result=handle.get_result_async();wait(result.done);assert result.result().status==4
        wait(lambda:lease.valid('follow'))
        assert received and lease.status['generation']>=generation+2
    finally:
        lease.stop();executor.shutdown();worker.join(timeout=3)
        server.destroy();client.destroy();proxy.server.destroy();proxy.client.destroy()
        for node in (backend,bridge,gateway):node.destroy_node()
        rclpy.try_shutdown()
