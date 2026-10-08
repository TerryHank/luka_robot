"""Real ROS services on isolated domain 188, using a fake case engine."""
import importlib.util
import os
from pathlib import Path
import time
import rclpy
from rclpy.node import Node
from rclpy.executors import SingleThreadedExecutor
from std_srvs.srv import Trigger


def test_gui_start_stop_without_hardware(tmp_path):
    assert os.environ.get("ROS_DOMAIN_ID")=="188"
    spec=importlib.util.spec_from_file_location("gui_launcher",Path(__file__).with_name("gui_launcher.py"))
    gui=importlib.util.module_from_spec(spec);spec.loader.exec_module(gui)
    class FakeEngine(gui.CaseEngine):
        def start(self,number,with_ekf=False,map_yaml=""):
            self.phase,self.case="running",number
        def stop(self):self.phase,self.case="idle",""
    engine=FakeEngine({"03":{"profile":"imu_launch"}},data=tmp_path)
    rclpy.init();node=gui.GuiLauncher(engine);client=Node("fake_gui_client")
    executor=SingleThreadedExecutor();executor.add_node(node);executor.add_node(client)
    start=client.create_client(Trigger,"/contract_demo/gui/start/03")
    stop=client.create_client(Trigger,"/contract_demo/gui/stop")
    def until(check):
        deadline=time.monotonic()+5
        while not check() and time.monotonic()<deadline:executor.spin_once(timeout_sec=.05)
        assert check()
    try:
        until(lambda:start.service_is_ready() and stop.service_is_ready())
        f=start.call_async(Trigger.Request());until(f.done);assert f.result().success
        until(lambda:engine.phase=="running" and not node.busy)
        f=stop.call_async(Trigger.Request());until(f.done);assert f.result().success
        until(lambda:engine.phase=="idle" and not node.busy)
    finally:
        if node.worker:node.worker.join()
        executor.shutdown();node.destroy_node();client.destroy_node();rclpy.shutdown()
