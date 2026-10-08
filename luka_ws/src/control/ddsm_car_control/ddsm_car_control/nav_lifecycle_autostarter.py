#!/usr/bin/env python3

from typing import Callable, Sequence

import rclpy
from nav2_msgs.srv import ManageLifecycleNodes
from rclpy.duration import Duration
from rclpy.node import Node
from rclpy.time import Time
from tf2_ros import Buffer, TransformException, TransformListener


class NavigationAutostartGate:
    """Starts Nav2 navigation only after localization has produced map->odom."""

    def __init__(
        self,
        has_localization_transform: Callable[[], bool],
        service_ready: Callable[[], bool],
        send_startup: Callable[[], bool],
    ):
        self._has_localization_transform = has_localization_transform
        self._service_ready = service_ready
        self._send_startup = send_startup
        self.started = False

    def tick(self) -> bool:
        if self.started:
            return True
        if not self._has_localization_transform():
            return False
        if not self._service_ready():
            return False

        self.started = self._send_startup()
        return self.started


class LifecycleBatchSequence:
    """Tracks lifecycle-manager services that must start in order."""

    def __init__(self, manager_services: Sequence[str]):
        services = [str(service) for service in manager_services if str(service)]
        if not services:
            raise ValueError("at least one lifecycle manager service is required")
        self.manager_services = services
        self.index = 0

    @property
    def completed(self) -> bool:
        return self.index >= len(self.manager_services)

    @property
    def current_service(self) -> str:
        if self.completed:
            raise IndexError("all lifecycle manager batches are complete")
        return self.manager_services[self.index]

    def advance(self) -> bool:
        if not self.completed:
            self.index += 1
        return self.completed


class NavigationLifecycleAutostarter(Node):
    def __init__(self):
        super().__init__("nav_lifecycle_autostarter")
        self.declare_parameter("map_frame", "map")
        self.declare_parameter("odom_frame", "odom")
        self.declare_parameter(
            "manager_service", "/lifecycle_manager_navigation/manage_nodes"
        )
        default_manager_service = self.get_parameter("manager_service").value
        self.declare_parameter("manager_services", [default_manager_service])
        self.declare_parameter("check_period", 1.0)

        self.map_frame = self.get_parameter("map_frame").value
        self.odom_frame = self.get_parameter("odom_frame").value
        manager_services = list(self.get_parameter("manager_services").value)
        self.sequence = LifecycleBatchSequence(manager_services)

        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        self.manager_clients = {
            service: self.create_client(ManageLifecycleNodes, service)
            for service in self.sequence.manager_services
        }
        self.pending_future = None

        self.gate = NavigationAutostartGate(
            has_localization_transform=self.has_localization_transform,
            service_ready=self.current_service_ready,
            send_startup=self.send_startup,
        )
        self.timer = self.create_timer(self.get_parameter("check_period").value, self.tick)
        self.get_logger().info(
            f"Waiting for {self.map_frame}->{self.odom_frame} before starting "
            f"{len(self.sequence.manager_services)} Nav2 lifecycle batch(es)"
        )

    def has_localization_transform(self) -> bool:
        try:
            return self.tf_buffer.can_transform(
                self.map_frame,
                self.odom_frame,
                Time(),
                timeout=Duration(seconds=0.05),
            )
        except TransformException:
            return False

    def current_service_ready(self) -> bool:
        if self.sequence.completed:
            return False
        return self.manager_clients[self.sequence.current_service].service_is_ready()

    def send_startup(self) -> bool:
        if self.pending_future is not None and not self.pending_future.done():
            return False

        service = self.sequence.current_service
        request = ManageLifecycleNodes.Request()
        request.command = ManageLifecycleNodes.Request.STARTUP
        self.pending_future = self.manager_clients[service].call_async(request)
        self.pending_future.add_done_callback(self.on_startup_response)
        self.get_logger().info(
            f"Localization is ready; starting Nav2 lifecycle batch "
            f"{self.sequence.index + 1}/{len(self.sequence.manager_services)}: {service}"
        )
        return True

    def on_startup_response(self, future) -> None:
        service = self.sequence.current_service
        try:
            response = future.result()
        except Exception as exc:
            self.get_logger().error(
                f"Navigation lifecycle batch call failed for {service}: {exc}"
            )
            self.gate.started = False
            self.pending_future = None
            return

        if not response.success:
            self.get_logger().warn(
                f"Nav2 lifecycle batch was rejected for {service}; retrying"
            )
            self.gate.started = False
            self.pending_future = None
            return

        self.get_logger().info(
            f"Nav2 lifecycle batch {self.sequence.index + 1}/"
            f"{len(self.sequence.manager_services)} startup succeeded: {service}"
        )
        self.pending_future = None
        if self.sequence.advance():
            self.get_logger().info("Nav2 navigation lifecycle startup succeeded")
            self.timer.cancel()
            return

        self.gate.started = False

    def tick(self) -> None:
        if not self.gate.tick():
            self.get_logger().debug(
                f"Still waiting for {self.map_frame}->{self.odom_frame} and lifecycle service"
            )


def main(args=None):
    rclpy.init(args=args)
    node = NavigationLifecycleAutostarter()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()
