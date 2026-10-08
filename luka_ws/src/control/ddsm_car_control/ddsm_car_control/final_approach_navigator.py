#!/usr/bin/env python3
import math
from dataclasses import dataclass
from typing import Optional, Sequence

import rclpy
from action_msgs.msg import GoalStatus
from geometry_msgs.msg import PoseStamped, Quaternion, Twist
from nav2_msgs.action import NavigateToPose
from rclpy.action import ActionClient
from rclpy.duration import Duration
from rclpy.node import Node
from rclpy.time import Time
from sensor_msgs.msg import LaserScan
from std_msgs.msg import Float32, String
from std_srvs.srv import Empty
from tf2_ros import Buffer, TransformException, TransformListener


@dataclass
class PlanarPose:
    x: float
    y: float
    yaw: float


@dataclass
class ServoCommand:
    linear_x: float
    linear_y: float
    angular_z: float
    reached: bool


@dataclass
class ScanLine:
    yaw: float
    residual: float
    point_count: int


def normalize_angle(angle: float) -> float:
    wrapped = (angle + math.pi) % (2.0 * math.pi) - math.pi
    if wrapped == -math.pi:
        return math.pi
    return wrapped


def clamp(value: float, lower: float, upper: float) -> float:
    return min(max(value, lower), upper)


def yaw_to_quaternion(yaw: float) -> Quaternion:
    quat = Quaternion()
    half = yaw * 0.5
    quat.x = 0.0
    quat.y = 0.0
    quat.z = math.sin(half)
    quat.w = math.cos(half)
    return quat


def yaw_from_quaternion(quat: Quaternion) -> float:
    return math.atan2(
        2.0 * (quat.w * quat.z + quat.x * quat.y),
        1.0 - 2.0 * (quat.y * quat.y + quat.z * quat.z),
    )


def pose_to_planar(pose: PoseStamped) -> PlanarPose:
    return PlanarPose(
        x=float(pose.pose.position.x),
        y=float(pose.pose.position.y),
        yaw=normalize_angle(yaw_from_quaternion(pose.pose.orientation)),
    )


def planar_to_pose_stamped(planar: PlanarPose, frame_id: str) -> PoseStamped:
    pose = PoseStamped()
    pose.header.frame_id = frame_id
    pose.pose.position.x = planar.x
    pose.pose.position.y = planar.y
    pose.pose.position.z = 0.0
    pose.pose.orientation = yaw_to_quaternion(planar.yaw)
    return pose


def compute_staging_pose(goal: PoseStamped, staging_distance: float) -> PoseStamped:
    goal_pose = pose_to_planar(goal)
    staging = PlanarPose(
        x=goal_pose.x - staging_distance * math.cos(goal_pose.yaw),
        y=goal_pose.y - staging_distance * math.sin(goal_pose.yaw),
        yaw=goal_pose.yaw,
    )
    pose = planar_to_pose_stamped(staging, goal.header.frame_id)
    pose.header.stamp = goal.header.stamp
    return pose


def compute_servo_command(
    robot: PlanarPose,
    goal: PlanarPose,
    *,
    xy_tolerance: float,
    yaw_tolerance: float,
    max_linear_speed: float,
    max_angular_speed: float,
    max_lateral_speed: float = 0.06,
    linear_gain: float = 0.45,
    lateral_gain: float = 0.45,
    heading_gain: float = 1.6,
    yaw_gain: float = 0.7,
    rotate_first_angle: float = 0.45,
    yaw_blend_distance: float = 0.35,
    allow_lateral_motion: bool = True,
    allow_position_motion: bool = True,
) -> ServoCommand:
    dx = goal.x - robot.x
    dy = goal.y - robot.y
    cos_yaw = math.cos(robot.yaw)
    sin_yaw = math.sin(robot.yaw)
    x_base = cos_yaw * dx + sin_yaw * dy
    y_base = -sin_yaw * dx + cos_yaw * dy
    distance = math.hypot(dx, dy)
    yaw_error = normalize_angle(goal.yaw - robot.yaw)

    if not allow_position_motion:
        if abs(yaw_error) <= yaw_tolerance:
            return ServoCommand(0.0, 0.0, 0.0, True)
        angular = clamp(yaw_gain * yaw_error, -max_angular_speed, max_angular_speed)
        return ServoCommand(0.0, 0.0, angular, False)

    if distance <= xy_tolerance and abs(yaw_error) <= yaw_tolerance:
        return ServoCommand(0.0, 0.0, 0.0, True)

    if allow_lateral_motion:
        linear_x = 0.0
        linear_y = 0.0
        if distance > xy_tolerance:
            linear_x = clamp(linear_gain * x_base, -max_linear_speed, max_linear_speed)
            linear_y = clamp(lateral_gain * y_base, -max_lateral_speed, max_lateral_speed)
        angular = clamp(yaw_gain * yaw_error, -max_angular_speed, max_angular_speed)
        return ServoCommand(linear_x, linear_y, angular, False)

    target_heading = math.atan2(y_base, x_base)
    if distance > xy_tolerance and abs(target_heading) > rotate_first_angle:
        angular = clamp(heading_gain * target_heading, -max_angular_speed, max_angular_speed)
        return ServoCommand(0.0, 0.0, angular, False)

    linear = clamp(linear_gain * x_base, -max_linear_speed, max_linear_speed)
    angular_target = heading_gain * target_heading
    if distance < yaw_blend_distance:
        angular_target += yaw_gain * yaw_error
    angular = clamp(angular_target, -max_angular_speed, max_angular_speed)

    if distance <= xy_tolerance:
        linear = 0.0
        angular = clamp(yaw_gain * yaw_error, -max_angular_speed, max_angular_speed)

    return ServoCommand(linear, 0.0, angular, False)


def compute_front_clearance(
    ranges: Sequence[float],
    angle_min: float,
    angle_increment: float,
    *,
    front_half_angle: float,
) -> float:
    front_ranges = []
    for index, distance in enumerate(ranges):
        angle = angle_min + float(index) * angle_increment
        if abs(angle) <= front_half_angle and math.isfinite(distance) and distance > 0.0:
            front_ranges.append(float(distance))
    if not front_ranges:
        return math.inf
    return min(front_ranges)


def fit_dominant_scan_line(
    ranges: Sequence[float],
    angle_min: float,
    angle_increment: float,
    *,
    max_range: float,
    front_half_angle: float,
    min_points: int,
) -> Optional[ScanLine]:
    points = []
    for index, distance in enumerate(ranges):
        angle = angle_min + float(index) * angle_increment
        if (
            abs(angle) <= front_half_angle
            and math.isfinite(distance)
            and 0.05 < distance <= max_range
        ):
            points.append((distance * math.cos(angle), distance * math.sin(angle)))

    if len(points) < min_points:
        return None

    cx = sum(point[0] for point in points) / len(points)
    cy = sum(point[1] for point in points) / len(points)
    sxx = sum((point[0] - cx) ** 2 for point in points) / len(points)
    syy = sum((point[1] - cy) ** 2 for point in points) / len(points)
    sxy = sum((point[0] - cx) * (point[1] - cy) for point in points) / len(points)
    yaw = 0.5 * math.atan2(2.0 * sxy, sxx - syy)
    residual = sum(
        abs(-math.sin(yaw) * (point[0] - cx) + math.cos(yaw) * (point[1] - cy))
        for point in points
    ) / len(points)
    return ScanLine(yaw=normalize_angle(yaw), residual=residual, point_count=len(points))


class DDSMFinalApproachNavigator(Node):
    def __init__(self) -> None:
        super().__init__("ddsm_final_approach_navigator")

        self.declare_parameter("goal_topic", "/goal_pose")
        self.declare_parameter("navigate_action", "navigate_to_pose")
        self.declare_parameter("cmd_vel_topic", "/cmd_vel_nav")
        self.declare_parameter("scan_topic", "/scan")
        self.declare_parameter("map_frame", "map")
        self.declare_parameter("base_frame", "base_link")
        self.declare_parameter("staging_distance", 0.75)
        self.declare_parameter("use_staging_pose", False)
        self.declare_parameter("final_servo_xy_enabled", False)
        self.declare_parameter("final_xy_tolerance", 0.08)
        self.declare_parameter("final_yaw_tolerance", 0.18)
        self.declare_parameter("servo_frequency", 10.0)
        self.declare_parameter("servo_timeout", 25.0)
        self.declare_parameter("max_final_linear_speed", 0.10)
        self.declare_parameter("max_final_lateral_speed", 0.06)
        self.declare_parameter("max_final_angular_speed", 0.45)
        self.declare_parameter("final_lateral_gain", 0.45)
        self.declare_parameter("allow_final_lateral_motion", True)
        self.declare_parameter("front_stop_distance", 0.30)
        self.declare_parameter("front_half_angle", 0.35)
        self.declare_parameter("laser_line_max_range", 3.0)
        self.declare_parameter("laser_line_min_points", 12)

        self.goal_topic = str(self.get_parameter("goal_topic").value)
        self.map_frame = str(self.get_parameter("map_frame").value)
        self.base_frame = str(self.get_parameter("base_frame").value)
        self.staging_distance = float(self.get_parameter("staging_distance").value)
        self.use_staging_pose = bool(self.get_parameter("use_staging_pose").value)
        self.final_servo_xy_enabled = bool(
            self.get_parameter("final_servo_xy_enabled").value
        )
        self.final_xy_tolerance = float(self.get_parameter("final_xy_tolerance").value)
        self.final_yaw_tolerance = float(self.get_parameter("final_yaw_tolerance").value)
        self.servo_timeout_s = float(self.get_parameter("servo_timeout").value)
        self.max_final_linear_speed = float(
            self.get_parameter("max_final_linear_speed").value
        )
        self.max_final_lateral_speed = float(
            self.get_parameter("max_final_lateral_speed").value
        )
        self.max_final_angular_speed = float(
            self.get_parameter("max_final_angular_speed").value
        )
        self.final_lateral_gain = float(self.get_parameter("final_lateral_gain").value)
        self.allow_final_lateral_motion = bool(
            self.get_parameter("allow_final_lateral_motion").value
        )
        self.front_stop_distance = float(self.get_parameter("front_stop_distance").value)
        self.front_half_angle = float(self.get_parameter("front_half_angle").value)
        self.laser_line_max_range = float(self.get_parameter("laser_line_max_range").value)
        self.laser_line_min_points = int(self.get_parameter("laser_line_min_points").value)

        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        self.action_client = ActionClient(
            self,
            NavigateToPose,
            str(self.get_parameter("navigate_action").value),
        )

        self.cmd_pub = self.create_publisher(
            Twist, str(self.get_parameter("cmd_vel_topic").value), 10
        )
        self.status_pub = self.create_publisher(String, "/final_approach/status", 10)
        self.staging_pub = self.create_publisher(
            PoseStamped, "/final_approach/staging_pose", 1
        )
        self.laser_line_pub = self.create_publisher(
            Float32, "/final_approach/laser_line_yaw", 10
        )

        self.create_subscription(PoseStamped, self.goal_topic, self.on_goal_pose, 10)
        self.scan_topic = str(self.get_parameter("scan_topic").value)
        self.scan_subscription = None
        self.create_service(Empty, "/final_approach/cancel", self.on_cancel)

        frequency = float(self.get_parameter("servo_frequency").value)
        self.servo_timer = self.create_timer(1.0 / frequency, self.on_servo_tick)
        self.servo_timer.cancel()
        self.servo_active = False
        self.servo_started_time = None
        self.final_goal: Optional[PoseStamped] = None
        self.current_goal_handle = None
        self.latest_scan: Optional[LaserScan] = None

        self.publish_status("idle")
        self.get_logger().info(
            "DDSM final approach ready | "
            f"goal_topic={self.goal_topic} use_staging={self.use_staging_pose} "
            f"xy_servo={self.final_servo_xy_enabled} staging_distance={self.staging_distance:.2f}m "
            f"lateral={self.allow_final_lateral_motion} vy_max={self.max_final_lateral_speed:.2f}m/s"
        )

    def publish_status(self, status: str) -> None:
        msg = String()
        msg.data = status
        self.status_pub.publish(msg)
        self.get_logger().info(f"final approach status: {status}")

    def on_scan(self, scan: LaserScan) -> None:
        self.latest_scan = scan
        if not self.servo_active:
            return
        line = fit_dominant_scan_line(
            scan.ranges,
            scan.angle_min,
            scan.angle_increment,
            max_range=self.laser_line_max_range,
            front_half_angle=self.front_half_angle,
            min_points=self.laser_line_min_points,
        )
        if line is not None:
            msg = Float32()
            msg.data = float(line.yaw)
            self.laser_line_pub.publish(msg)

    def enable_scan_subscription(self) -> None:
        if self.scan_subscription is None:
            self.scan_subscription = self.create_subscription(
                LaserScan, self.scan_topic, self.on_scan, 10
            )

    def disable_scan_subscription(self) -> None:
        if self.scan_subscription is not None:
            self.destroy_subscription(self.scan_subscription)
            self.scan_subscription = None
        self.latest_scan = None

    def on_goal_pose(self, goal: PoseStamped) -> None:
        if goal.header.frame_id and goal.header.frame_id != self.map_frame:
            self.publish_status(f"rejected_goal_frame:{goal.header.frame_id}")
            self.get_logger().warn(
                f"goal frame must be {self.map_frame}, got {goal.header.frame_id}"
            )
            return

        self.stop_robot()
        self.servo_active = False
        self.servo_timer.cancel()
        self.disable_scan_subscription()
        self.final_goal = goal
        if self.use_staging_pose:
            nav_goal = compute_staging_pose(goal, self.staging_distance)
            nav_goal.header.stamp = self.get_clock().now().to_msg()
            self.staging_pub.publish(nav_goal)
            self.publish_status("navigating_to_staging")
            self.send_nav_goal(nav_goal, "staging", self.start_final_servo)
            return

        nav_goal = PoseStamped()
        nav_goal.header = goal.header
        nav_goal.header.stamp = self.get_clock().now().to_msg()
        nav_goal.pose.position = goal.pose.position
        # Nav2 now checks yaw as well as XY. Preserve the requested heading;
        # using the departure heading here would cause an unnecessary turn
        # before the final servo turns back to the waypoint heading.
        nav_goal.pose.orientation = goal.pose.orientation
        self.publish_status("navigating_to_final_xy")
        self.send_nav_goal(nav_goal, "final_nav_xy", self.start_final_servo)

    def send_nav_goal(self, pose: PoseStamped, label: str, done_callback) -> None:
        if not self.action_client.wait_for_server(timeout_sec=2.0):
            self.publish_status(f"{label}_nav_server_unavailable")
            return

        goal = NavigateToPose.Goal()
        goal.pose = pose
        future = self.action_client.send_goal_async(goal)
        future.add_done_callback(
            lambda response_future: self.on_nav_goal_response(
                response_future, label, done_callback
            )
        )

    def on_nav_goal_response(self, future, label: str, done_callback) -> None:
        goal_handle = future.result()
        if not goal_handle.accepted:
            self.publish_status(f"{label}_goal_rejected")
            return
        self.current_goal_handle = goal_handle
        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(
            lambda nav_future: self.on_nav_result(nav_future, label, done_callback)
        )

    def on_nav_result(self, future, label: str, done_callback) -> None:
        result = future.result()
        self.current_goal_handle = None
        if result.status != GoalStatus.STATUS_SUCCEEDED:
            self.publish_status(f"{label}_failed:{result.status}")
            return
        self.publish_status(f"{label}_reached")
        done_callback()

    def start_final_servo(self) -> None:
        if self.final_goal is None:
            self.publish_status("missing_final_goal")
            return
        self.servo_started_time = self.get_clock().now()
        self.servo_active = True
        self.enable_scan_subscription()
        self.servo_timer.reset()
        self.publish_status("final_servo")

    def on_servo_tick(self) -> None:
        if not self.servo_active or self.final_goal is None:
            return

        if self.servo_started_time is not None:
            elapsed = self.get_clock().now() - self.servo_started_time
            if elapsed > Duration(seconds=self.servo_timeout_s):
                self.servo_active = False
                self.servo_timer.cancel()
                self.disable_scan_subscription()
                self.stop_robot()
                self.publish_status("final_servo_timeout")
                return

        if self.latest_scan is not None:
            clearance = compute_front_clearance(
                self.latest_scan.ranges,
                self.latest_scan.angle_min,
                self.latest_scan.angle_increment,
                front_half_angle=self.front_half_angle,
            )
            if clearance < self.front_stop_distance:
                self.servo_active = False
                self.servo_timer.cancel()
                self.disable_scan_subscription()
                self.stop_robot()
                self.publish_status(f"blocked_front:{clearance:.2f}")
                return

        try:
            transform = self.tf_buffer.lookup_transform(
                self.map_frame,
                self.base_frame,
                Time(),
                timeout=Duration(seconds=0.2),
            )
        except TransformException as exc:
            self.get_logger().warn(f"waiting for TF {self.map_frame}->{self.base_frame}: {exc}")
            return

        robot = PlanarPose(
            x=float(transform.transform.translation.x),
            y=float(transform.transform.translation.y),
            yaw=normalize_angle(yaw_from_quaternion(transform.transform.rotation)),
        )
        command = compute_servo_command(
            robot,
            pose_to_planar(self.final_goal),
            xy_tolerance=self.final_xy_tolerance,
            yaw_tolerance=self.final_yaw_tolerance,
            max_linear_speed=self.max_final_linear_speed,
            max_lateral_speed=self.max_final_lateral_speed,
            max_angular_speed=self.max_final_angular_speed,
            lateral_gain=self.final_lateral_gain,
            allow_lateral_motion=self.allow_final_lateral_motion,
            allow_position_motion=self.final_servo_xy_enabled,
        )
        if command.reached:
            self.servo_active = False
            self.servo_timer.cancel()
            self.disable_scan_subscription()
            self.stop_robot()
            self.publish_status("final_reached")
            return

        twist = Twist()
        twist.linear.x = command.linear_x
        twist.linear.y = command.linear_y
        twist.angular.z = command.angular_z
        self.cmd_pub.publish(twist)

    def stop_robot(self) -> None:
        self.cmd_pub.publish(Twist())

    def on_cancel(self, _request, response):
        self.servo_active = False
        self.servo_timer.cancel()
        self.disable_scan_subscription()
        self.stop_robot()
        if self.current_goal_handle is not None:
            self.current_goal_handle.cancel_goal_async()
            self.current_goal_handle = None
        self.publish_status("cancelled")
        return response


def main(args=None) -> None:
    rclpy.init(args=args)
    node = DDSMFinalApproachNavigator()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.stop_robot()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
