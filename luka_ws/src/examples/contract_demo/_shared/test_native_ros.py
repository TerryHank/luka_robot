"""Isolated ROS transport acceptance; refuses the robot's production domain."""
import importlib.util
import os
from pathlib import Path
import time
from unittest.mock import patch
import rclpy
from rclpy.action import ActionServer
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from geometry_msgs.msg import PoseStamped
from nav2_msgs.action import NavigateToPose
from std_srvs.srv import SetBool, Trigger


def test_staging_gate_and_action_roundtrip(tmp_path):
    assert os.environ.get("ROS_DOMAIN_ID") == "188", "Transport test requires isolated domain 188"
    spec = importlib.util.spec_from_file_location("native_commands", Path(__file__).with_name("native_commands.py"))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    rclpy.init()
    fake = Node("fake_nav2_and_base")
    permitted, received = [False], []
    def gate(request, response):
        response.success = permitted[0] if request.data else True
        response.message = "fake gate only"
        return response
    fake.create_service(SetBool, "/nx/navigation_enable", gate)
    def execute(handle):
        received.append(handle.request.pose)
        handle.succeed()
        return NavigateToPose.Result()
    server = ActionServer(fake, NavigateToPose, "navigate_to_pose", execute)
    with patch.object(module.Path, "home", return_value=tmp_path):
        adapter = module.NativeCommands()
    executor = MultiThreadedExecutor(num_threads=2)
    executor.add_node(adapter); executor.add_node(fake)
    publisher = fake.create_publisher(PoseStamped, "/contract_demo/goal_pose", 10)
    send = fake.create_client(Trigger, "/contract_demo/send_goal")
    def until(check):
        deadline = time.monotonic()+8
        while not check() and time.monotonic()<deadline:
            executor.spin_once(timeout_sec=.05)
        assert check()
    try:
        until(lambda: adapter.nav.server_is_ready() and adapter.gate.service_is_ready() and send.service_is_ready() and publisher.get_subscription_count()==1)
        pose = PoseStamped(); pose.header.frame_id = "map"; pose.pose.orientation.w = 1.; pose.pose.position.x = .5
        publisher.publish(pose)
        until(lambda: adapter.state.get("state")=="staged")
        assert received == []
        request = send.call_async(Trigger.Request()); until(request.done)
        until(lambda: adapter.state.get("state")=="gate_rejected")
        assert received == []
        permitted[0] = True
        publisher.publish(pose); until(lambda: adapter.state.get("state")=="staged")
        request = send.call_async(Trigger.Request()); until(request.done)
        until(lambda: adapter.state.get("state")=="finished")
        assert len(received)==1 and received[0].pose.position.x==.5
        assert adapter.state["action_status"]==4
    finally:
        stopped = adapter.abort("test cleanup")
        if stopped is not None:
            until(stopped.done)
        server.destroy(); executor.shutdown(); adapter.destroy_node(); fake.destroy_node(); rclpy.shutdown()
