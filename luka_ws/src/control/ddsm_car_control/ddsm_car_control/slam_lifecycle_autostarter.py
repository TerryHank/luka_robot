#!/usr/bin/env python3

import time

import rclpy
from lifecycle_msgs.msg import State, Transition
from lifecycle_msgs.srv import ChangeState, GetState
from rclpy.node import Node


def normalize_target_node(target_node):
    if not target_node:
        return "/slam_toolbox"
    if target_node.startswith("/"):
        return target_node
    return f"/{target_node}"


def startup_transition_for_state(state_id):
    if state_id == State.PRIMARY_STATE_UNCONFIGURED:
        return Transition.TRANSITION_CONFIGURE
    if state_id == State.PRIMARY_STATE_INACTIVE:
        return Transition.TRANSITION_ACTIVATE
    return None


def pending_request_timed_out(started_at, now, timeout_seconds):
    if started_at is None:
        return False
    return now - started_at >= timeout_seconds


def transition_name(transition_id):
    if transition_id == Transition.TRANSITION_CONFIGURE:
        return "configure"
    if transition_id == Transition.TRANSITION_ACTIVATE:
        return "activate"
    return str(transition_id)


class SlamLifecycleAutostarter(Node):
    def __init__(self):
        super().__init__("slam_lifecycle_autostarter")
        self.declare_parameter("target_node", "/slam_toolbox")
        self.declare_parameter("check_period", 1.0)
        self.declare_parameter("request_timeout", 5.0)

        self.target_node = normalize_target_node(
            self.get_parameter("target_node").value
        )
        check_period = float(self.get_parameter("check_period").value)
        self.request_timeout = float(self.get_parameter("request_timeout").value)

        self.get_state_client = self.create_client(
            GetState, f"{self.target_node}/get_state"
        )
        self.change_state_client = self.create_client(
            ChangeState, f"{self.target_node}/change_state"
        )
        self.pending_future = None
        self.pending_started_at = None
        self.timer = self.create_timer(check_period, self.tick)
        self.get_logger().info(
            f"Waiting to activate {self.target_node} before Nav2 startup"
        )

    def tick(self):
        if self.pending_future is not None:
            if not pending_request_timed_out(
                self.pending_started_at, time.monotonic(), self.request_timeout
            ):
                return
            self.get_logger().warn(
                f"Timed out waiting for {self.target_node} lifecycle service response; retrying"
            )
            self.pending_future = None
            self.pending_started_at = None
        if not self.get_state_client.service_is_ready():
            self.get_logger().debug(f"Waiting for {self.target_node}/get_state")
            return

        request = GetState.Request()
        self.track_pending_future(self.get_state_client.call_async(request))
        self.pending_future.add_done_callback(self.handle_state_response)

    def track_pending_future(self, future):
        self.pending_future = future
        self.pending_started_at = time.monotonic()

    def handle_state_response(self, future):
        if future is not self.pending_future:
            return
        self.pending_future = None
        self.pending_started_at = None
        try:
            response = future.result()
        except Exception as exc:  # pragma: no cover - rclpy transport error path
            self.get_logger().warn(f"Failed to query {self.target_node} state: {exc}")
            return

        state_id = response.current_state.id
        if state_id == State.PRIMARY_STATE_ACTIVE:
            self.get_logger().info(f"{self.target_node} is active")
            self.timer.cancel()
            return

        transition_id = startup_transition_for_state(state_id)
        if transition_id is None:
            self.get_logger().debug(
                f"{self.target_node} state {state_id} is not ready for startup transition"
            )
            return
        if not self.change_state_client.service_is_ready():
            self.get_logger().debug(f"Waiting for {self.target_node}/change_state")
            return

        request = ChangeState.Request()
        request.transition.id = transition_id
        self.track_pending_future(self.change_state_client.call_async(request))
        self.pending_future.add_done_callback(
            lambda transition_future: self.handle_transition_response(
                transition_future, transition_id
            )
        )

    def handle_transition_response(self, future, transition_id):
        if future is not self.pending_future:
            return
        self.pending_future = None
        self.pending_started_at = None
        try:
            response = future.result()
        except Exception as exc:  # pragma: no cover - rclpy transport error path
            self.get_logger().warn(
                f"Failed to {transition_name(transition_id)} {self.target_node}: {exc}"
            )
            return

        if response.success:
            self.get_logger().info(
                f"Requested {transition_name(transition_id)} for {self.target_node}"
            )
            return

        self.get_logger().warn(
            f"{self.target_node} rejected {transition_name(transition_id)}; retrying"
        )


def main(args=None):
    rclpy.init(args=args)
    node = SlamLifecycleAutostarter()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
