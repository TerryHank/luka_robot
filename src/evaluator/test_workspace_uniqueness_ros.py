"""Canonical command delegation tests; localhost mocks only, no real motion."""
import concurrent.futures
import importlib.util
import os
from pathlib import Path
import subprocess
import threading
import time
from types import SimpleNamespace

os.environ['ROS_DOMAIN_ID']='98'
os.environ['ROS_LOCALHOST_ONLY']='1'
import pytest
import rclpy
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import QoSProfile,DurabilityPolicy
from std_msgs.msg import String
from std_srvs.srv import SetBool

root=Path('/home/sunrise/luka_ws')
spec=importlib.util.spec_from_file_location('canonical_dashboard_follow',root/'src/visualization/console/nx_follow.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


def test_command_facade_modes_identity_rejection_and_stop_race():
    rclpy.init()
    server=Node('tros_person_following_node',namespace='/person_follow')
    server.declare_parameter('output_mode','dry_run')
    calls=[]
    delay=[0.0]
    actual=[False]
    def service(request,response):
        calls.append(request.data)
        if request.data:time.sleep(delay[0])
        actual[0]=request.data
        response.success=True
        return response
    server.create_service(SetBool,'enable_follow',service,callback_group=ReentrantCallbackGroup())
    client=Node('dashboard_facade_test')
    client.nx_handle=None
    client.patrol_mission=SimpleNamespace(active=lambda:False)
    client.relocalization=SimpleNamespace(running=False)
    controller=module.FollowController(client)
    executor=MultiThreadedExecutor(num_threads=4)
    executor.add_node(server);executor.add_node(client)
    thread=threading.Thread(target=executor.spin,daemon=True);thread.start()
    def wait_until(predicate,timeout=3.0):
        end=time.monotonic()+timeout
        while not predicate() and time.monotonic()<end:time.sleep(.01)
        assert predicate()
    try:
        wait_until(lambda:controller.output_mode=='dry_run' and controller.gate.service_is_ready())
        assert not controller.enabled
        for kwargs in [{'mode':'profile'},{'mode':'track','expected_track_id':42},
                       {'expected_profile_id':'owner'}]:
            with pytest.raises(ValueError,match='不支持'):controller.start(**kwargs)
        assert calls==[]
        result=controller.start()
        assert result['enabled'] and result['output_mode']=='dry_run' and calls==[True]
        assert result['forward_m_s'] is None and result['yaw_rad_s'] is None
        controller.stop()
        wait_until(lambda:not controller.enabled and not actual[0])
        publishers=client.get_publisher_names_and_types_by_node(client.get_name(),client.get_namespace())
        assert all('geometry_msgs/msg/Twist' not in types for _,types in publishers)
        client.nx_handle=object()
        with pytest.raises(ValueError,match='结束导航'):controller.start()
        client.nx_handle=None
        before=len(calls)
        delay[0]=.3
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(controller.start)
            wait_until(lambda:len(calls)>before)
            controller.stop()
            with pytest.raises(ValueError,match='停止请求'):future.result(timeout=3)
        wait_until(lambda:not actual[0] and not controller.enabled)
        assert calls[-1] is False
        delay[0]=3.3
        with pytest.raises(ValueError,match='未确认启用'):controller.start()
        time.sleep(.5)
        wait_until(lambda:not actual[0] and not controller.enabled)
        assert calls[-1] is False
    finally:
        executor.shutdown(timeout_sec=3)
        client.destroy_node();server.destroy_node();rclpy.shutdown()


def test_camera_entrypoints_refuse_existing_owner_before_hardware_start():
    import fcntl
    lock=root/'log/owners/astra-camera.lock'
    lock.parent.mkdir(exist_ok=True)
    with lock.open('w') as held:
        try:
            fcntl.flock(held,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            # An existing canonical owner is already a valid occupied-lock fixture.
            pass
        for script in ['start_orbbec_camera.sh']:
            result=subprocess.run(['bash',str(root/'src/system/scripts'/script)],
                                  capture_output=True,text=True,timeout=10)
            assert result.returncode==1
            assert 'already owned' in result.stderr


def test_compatibility_launch_delegates_to_canonical_defaults():
    alias = (root/'src/system/scripts/start_selected_follow_preview.sh').read_text()
    canonical = (root/'src/system/scripts/start_official_person_following.sh').read_text()
    assert 'start_official_person_following.sh' in alias
    assert 'ros2 launch luka_person_following' not in alias
    assert 's100_person_following_integration' in canonical
