#!/usr/bin/env python3
"""Foxglove ROS command adapter. Nav2 remains the navigation controller.

No HTTP server or velocity publisher. Drawing a pose only stages a goal;
the operator must separately invoke send_goal. All motion uses the base gate.
"""
import copy
import fcntl
import json
import math
from pathlib import Path
import subprocess
import sys
import threading
import time

import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node
from geometry_msgs.msg import PoseStamped
from nav2_msgs.action import NavigateToPose
from std_msgs.msg import String
from std_srvs.srv import SetBool, Trigger

def valid_pose(pose):
    p, q = pose.pose.position, pose.pose.orientation
    values = (p.x, p.y, p.z, q.x, q.y, q.z, q.w)
    return pose.header.frame_id == "map" and all(math.isfinite(v) for v in values) \
        and abs(sum(v*v for v in values[3:]) - 1.0) < .01


class NativeCommands(Node):
    def __init__(self):
        super().__init__("contract_demo_native")
        root = Path.home() / "luka_data/recordings/contract_demo"
        root.mkdir(parents=True, exist_ok=True)
        self.lock = (root / "native_command_owner.lock").open("w")
        fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.nav = ActionClient(self, NavigateToPose, "navigate_to_pose")
        self.gate = self.create_client(SetBool, "/nx/navigation_enable")
        self.output = self.create_publisher(String, "/contract_demo/navigation_status", 10)
        self.map_output = self.create_publisher(String, "/contract_demo/map_status", 10)
        self.create_subscription(PoseStamped, "/contract_demo/goal_pose", self.stage, 10)
        self.create_service(Trigger, "/contract_demo/send_goal", self.send)
        self.create_service(Trigger, "/contract_demo/cancel_goal", self.cancel)
        self.create_service(Trigger, "/contract_demo/save_map", self.save_map)
        self.goal = None
        self.goal_at = 0.
        self.goal_handle = None
        self.pending = False
        self.generation = 0
        self.deadline = 0.
        self.state = {"state": "idle"}
        self.map_state = {"state": "idle"}
        self.map_busy = False
        self.create_timer(.25, self.tick)

    def update(self, state, **fields):
        self.state = dict(state=state, **fields)

    def stage(self, pose):
        if not valid_pose(pose):
            self.goal = None
            self.update("invalid_pose", reason="Require finite unit-quaternion pose in map")
            return
        if self.pending:
            self.update("busy", reason="Cancel the active navigation first")
            return
        self.goal, self.goal_at = copy.deepcopy(pose), time.monotonic()
        self.update("staged", x=pose.pose.position.x, y=pose.pose.position.y,
                    note="Not sent to Nav2; click execute within 30 seconds")

    def send(self, _request, response):
        response.success = False
        if self.pending:
            response.message = "An active goal exists; cancel and confirm stopped first"
        elif self.goal is None or time.monotonic() - self.goal_at > 30:
            response.message = "Draw a fresh map-frame goal in 3D first (30s expiry)"
        elif not self.nav.server_is_ready() or not self.gate.service_is_ready():
            response.message = "Nav2 action server or protected base gate unavailable"
        else:
            self.pending = True
            self.generation += 1
            generation = self.generation
            self.deadline = time.monotonic() + 3
            goal = copy.deepcopy(self.goal)
            self.goal = None
            self.update("checking_base_gate")
            future = self.gate.call_async(SetBool.Request(data=True))
            future.add_done_callback(lambda f: self.enabled(f, goal, generation))
            response.success, response.message = True, "Checking safety gate; watch navigation_status"
        return response

    def enabled(self, future, pose, generation):
        if generation != self.generation:
            self.disable()
            return
        try:
            result = future.result()
            if not result.success:
                self.pending = False
                self.update("gate_rejected", reason=result.message)
                return
            pose.header.stamp = self.get_clock().now().to_msg()
            self.deadline = time.monotonic() + 3
            self.update("awaiting_nav2")
            self.nav.send_goal_async(NavigateToPose.Goal(pose=pose),
                                     feedback_callback=self.feedback).add_done_callback(
                lambda f: self.accepted(f, generation))
        except Exception as error:
            self.abort(str(error))

    def accepted(self, future, generation):
        try:
            handle = future.result()
            if generation != self.generation:
                if handle.accepted:
                    handle.cancel_goal_async()
                self.disable()
                return
            if not handle.accepted:
                self.abort("Nav2 rejected goal")
                return
            self.goal_handle = handle
            self.deadline = 0
            self.update("executing")
            handle.get_result_async().add_done_callback(lambda f: self.finished(f, generation))
        except Exception as error:
            self.abort(str(error))

    def feedback(self, event):
        if self.pending and self.goal_handle:
            self.update("executing", distance_remaining=event.feedback.distance_remaining)

    def finished(self, future, generation):
        if generation != self.generation:
            return
        try:
            self.update("finished", action_status=future.result().status,
                        note="Check measured odometry for stop confirmation")
        except Exception as error:
            self.update("failed", reason=str(error))
        self.pending, self.goal_handle, self.deadline = False, None, 0
        self.disable()

    def disable(self):
        if self.gate.service_is_ready():
            return self.gate.call_async(SetBool.Request(data=False))

    def abort(self, reason):
        self.generation += 1
        if self.goal_handle:
            self.goal_handle.cancel_goal_async()
        self.pending, self.goal_handle, self.deadline = False, None, 0
        stopped = self.disable()
        self.update("cancel_requested", reason=reason, note="Confirm measured stop")
        return stopped

    def cancel(self, _request, response):
        self.abort("Operator cancel")
        self.goal = None
        response.success, response.message = True, "Cancel requested; check measured stop"
        return response

    def tick(self):
        if self.pending and self.deadline and time.monotonic() > self.deadline:
            self.abort("Safety gate/action acknowledgement timeout")
        self.output.publish(String(data=json.dumps(self.state)))
        self.map_output.publish(String(data=json.dumps(self.map_state)))

    def save_map(self, _request, response):
        if self.map_busy:
            response.success, response.message = False, "Map export already running"
            return response
        self.map_busy = True
        self.map_state = {"state": "saving"}
        def export():
            try:
                result = subprocess.run([sys.executable, str(Path(__file__).with_name("save_map.py")),
                                         "foxglove_demo"], capture_output=True, text=True, timeout=80)
                self.map_state = dict(state="saved" if result.returncode == 0 else "failed",
                                      message=(result.stdout + result.stderr)[-3000:])
            except (OSError, subprocess.TimeoutExpired) as error:
                self.map_state = dict(state="failed", message=str(error))
            finally:
                self.map_busy = False
        threading.Thread(target=export, daemon=True).start()
        response.success, response.message = True, "Export started; watch /contract_demo/map_status"
        return response


def main():
    rclpy.init()
    node = NativeCommands()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if rclpy.ok():
            stopped = node.abort("Command adapter shutdown")
            if stopped is not None:
                rclpy.spin_until_future_complete(node, stopped, timeout_sec=1.)
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
