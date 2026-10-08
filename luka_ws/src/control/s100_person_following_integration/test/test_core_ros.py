"""Synthetic TF/perception and mock Nav2 only; no motor command publishers."""
import math
import os
import signal
import subprocess
import threading
import time

import pytest

# Per-test-process transport isolation; never affect the production graph.
os.environ['ROS_DOMAIN_ID'] = '73'
os.environ['ROS_LOCALHOST_ONLY'] = '1'
import rclpy
from rclpy.action import ActionClient, ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import QoSProfile, DurabilityPolicy
from ai_msgs.msg import PerceptionTargets, Target, Roi, Attribute
from geometry_msgs.msg import PoseStamped, TransformStamped
from nav_msgs.msg import OccupancyGrid, Odometry
from nav2_msgs.action import NavigateToPose, Spin
from std_msgs.msg import String
from std_srvs.srv import SetBool
from tf2_ros import TransformBroadcaster, StaticTransformBroadcaster


class Harness:
    index = 0

    def __init__(self, tmp_path, mode='dry_run', server=True, delay=0.0, reject=False,
                 overrides=None, spin_server=True, spin_delay=0.0, spin_reject=False):
        # Independent domains avoid DDS discovery residue between fault cases.
        domain = 73 + Harness.index
        if domain >= 87: domain += 1  # The production robot uses 87.
        Harness.index += 1
        os.environ['ROS_DOMAIN_ID'] = str(domain)
        rclpy.init()
        self.node = Node('follow_test_harness')
        self.executor = MultiThreadedExecutor(num_threads=4)
        self.executor.add_node(self.node)
        self.thread = threading.Thread(target=self.executor.spin, daemon=True)
        self.thread.start()
        self.candidates, self.status, self.diagnostics = [], [], []
        self.goals, self.cancels, self.handles = [], [], []
        self.spins, self.spin_cancels, self.spin_handles, self.spin_candidates = [], [], [], []
        self.spin_delay, self.spin_reject, self.spin_finish = spin_delay, spin_reject, None
        self.nav_auto_finish = False
        self.robot_x, self.robot_y, self.robot_yaw = 1.0, 2.0, math.pi / 2
        self.bbox_x, self.bbox_width = 250, 150
        self.nav_events, self.spin_events = [], []
        self.odom_enabled, self.odom_velocity = True, 0.
        self.tf_enabled, self.map_enabled, self.people_enabled = True, True, True
        self.people, self.age, self.bad_map = [(42, 2.4, 0.0)], 0.0, None
        self.dynamic = TransformBroadcaster(self.node)
        self.static = StaticTransformBroadcaster(self.node)
        camera = TransformStamped()
        camera.header.frame_id, camera.child_frame_id = 'base_link', 'camera_link'
        camera.transform.translation.x = 0.2
        camera.transform.rotation.w = 1.0
        self.static.sendTransform(camera)
        self.perception = self.node.create_publisher(PerceptionTargets, '/test/detections', 10)
        self.odometry = self.node.create_publisher(Odometry, '/test/odom', 10)
        self.costmap = self.node.create_publisher(OccupancyGrid, '/test/costmap',
            QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL))
        self.node.create_subscription(PoseStamped, '/test/candidate', self.candidates.append, 10)
        self.node.create_subscription(String, '/follow/tros_tracking_status',
                                      lambda m: self.status.append(m.data), 10)
        self.node.create_subscription(String, '/follow/integration_diagnostics',
                                      lambda m: self.diagnostics.append(m.data), 10)
        self.node.create_subscription(PoseStamped, '/test/spin_candidate', self.spin_candidates.append, 10)
        self.service = self.node.create_client(SetBool, '/follow/enable_follow')
        self.server = None
        self.running = True
        self.delay, self.reject = delay, reject
        self.finish_code = None
        if server:
            self.server = ActionServer(self.node, NavigateToPose, '/test/navigate',
                execute_callback=self.execute, goal_callback=self.accept,
                cancel_callback=self.cancel, callback_group=ReentrantCallbackGroup())
        self.spin_server = None
        if spin_server:
            self.spin_server = ActionServer(self.node, Spin, '/test/spin',
                execute_callback=self.execute_spin, goal_callback=self.accept_spin,
                cancel_callback=self.cancel_spin, callback_group=ReentrantCallbackGroup())
        self.external_spin = ActionClient(self.node, Spin, '/test/spin')
        self.external = ActionClient(self.node, NavigateToPose, '/test/navigate')
        self.timer = self.node.create_timer(0.05, self.publish)
        exe = '/home/sunrise/luka_ws/install/tros_person_following/lib/tros_person_following/tros_person_following'
        log = open(tmp_path / 'core.log', 'w')
        args = [exe, '--ros-args', '-r', '__ns:=/follow']
        params = {'output_mode': mode, 'global_frame': 'map', 'robot_frame': 'base_link',
                  'camera_frame': 'camera_link', 'detect_result_topic_name': '/test/detections',
                  'costmap_topic': '/test/costmap', 'navigate_to_pose_action_name': '/test/navigate',
                  'goal_candidate_topic': '/test/candidate', 'single_person_auto_relock': False,
                  'buzzer_min_interval_sec': -1.0, 'follow_distance_min': 1.8,
                  'follow_distance_max': 2.0, 'target_filter_range_x_max': 8.0,
                  'target_filter_range_y_max': 4.0, 'target_filter_range_y_min': -4.0,
                  'static_target_move_thr': 0.05, 'static_switch_activity_window_sec': 0.5,
                  'idle_observe_duration_sec': 2.0, 'input_timeout_sec': 0.6,
                  'tracking_to_lost_timeout_sec': 0.2, 'belief_search_timeout_sec': 1.0,
                  'lost_to_idle_timeout_sec': 0.5,
                  'spin_action_name': '/test/spin', 'spin_candidate_topic': '/test/spin_candidate',
                  'odometry_topic': '/test/odom'}
        params.update(overrides or {})
        for k, v in params.items():
            args += ['-p', f'{k}:={str(v).lower() if isinstance(v, bool) else v}']
        self.process = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT)
        self.log = log
        assert self.service.wait_for_service(timeout_sec=5.0)
        self.wait(0.5)

    def accept(self, request):
        if request.pose.pose.position.x != 99.0:
            time.sleep(self.delay)
        return GoalResponse.REJECT if self.reject and request.pose.pose.position.x != 99.0 else GoalResponse.ACCEPT

    def execute(self, handle):
        # Let the accepted-goal response travel before the mock control loop starts.
        time.sleep(.1)
        self.handles.append(handle)
        self.goals.append(handle.request.pose)
        self.nav_events.append(('start', time.monotonic(), bytes(handle.goal_id.uuid)))
        if self.nav_auto_finish and handle.request.pose.pose.position.x != 99.0:
            self.robot_x = handle.request.pose.pose.position.x
            self.robot_y = handle.request.pose.pose.position.y
            q = handle.request.pose.pose.orientation
            self.robot_yaw = 2 * math.atan2(q.z, q.w)
            # A real arrival has pose feedback before the Action success result.
            self.publish()
            time.sleep(.1)
            handle.succeed()
            self.nav_events.append(('end', time.monotonic(), bytes(handle.goal_id.uuid)))
            return NavigateToPose.Result()
        while self.running and not handle.is_cancel_requested and self.finish_code is None:
            feedback = NavigateToPose.Feedback()
            feedback.distance_remaining = 1.0
            handle.publish_feedback(feedback)
            time.sleep(0.05)
        if handle.is_cancel_requested:
            handle.canceled()
        elif self.finish_code == 'abort':
            handle.abort()
        else:
            handle.succeed()
        self.nav_events.append(('end', time.monotonic(), bytes(handle.goal_id.uuid)))
        return NavigateToPose.Result()

    def accept_spin(self, request):
        if request.target_yaw != 99.0: time.sleep(self.spin_delay)
        return GoalResponse.REJECT if self.spin_reject and request.target_yaw != 99.0 else GoalResponse.ACCEPT

    def execute_spin(self, handle):
        time.sleep(.1)
        self.spin_handles.append(handle)
        self.spins.append(handle.request.target_yaw)
        self.spin_events.append(('start', time.monotonic(), bytes(handle.goal_id.uuid)))
        while self.running and not handle.is_cancel_requested:
            if handle.request.target_yaw != 99.0 and self.spin_finish is not None: break
            feedback = Spin.Feedback();feedback.angular_distance_traveled = .1
            handle.publish_feedback(feedback)
            time.sleep(.02)
        if handle.is_cancel_requested: handle.canceled()
        elif self.spin_finish == 'abort': handle.abort()
        else: handle.succeed()
        self.spin_events.append(('end', time.monotonic(), bytes(handle.goal_id.uuid)))
        return Spin.Result()

    def cancel_spin(self, handle):
        self.spin_cancels.append(bytes(handle.goal_id.uuid))
        return CancelResponse.ACCEPT

    def cancel(self, handle):
        self.cancels.append(bytes(handle.goal_id.uuid))
        return CancelResponse.ACCEPT

    def publish(self):
        stamp = self.node.get_clock().now().to_msg()
        if self.odom_enabled:
            odom=Odometry();odom.header.stamp=stamp
            odom.header.frame_id,odom.child_frame_id='odom','base_link'
            odom.twist.twist.angular.z=self.odom_velocity
            self.odometry.publish(odom)
        if self.tf_enabled:
            tf = TransformStamped()
            tf.header.stamp, tf.header.frame_id, tf.child_frame_id = stamp, 'map', 'base_link'
            tf.transform.translation.x, tf.transform.translation.y = self.robot_x, self.robot_y
            tf.transform.rotation.z = math.sin(self.robot_yaw / 2)
            tf.transform.rotation.w = math.cos(self.robot_yaw / 2)
            self.dynamic.sendTransform(tf)
        if self.map_enabled:
            cm = OccupancyGrid()
            cm.header.stamp, cm.header.frame_id = stamp, 'map'
            cm.info.resolution, cm.info.width, cm.info.height = 0.2, 100, 100
            cm.info.origin.position.x, cm.info.origin.position.y = -5.0, -5.0
            cm.info.origin.orientation.w = 1.0
            cm.data = [0] * 10000
            if self.bad_map == 'unknown': cm.data = [-1] * 10000
            if self.bad_map == 'occupied': cm.data = [100] * 10000
            if self.bad_map == 'short': cm.data = [0]
            if self.bad_map == 'frame': cm.header.frame_id = 'wrong_map'
            if self.bad_map == 'rotated': cm.info.origin.orientation.z = 0.3
            self.costmap.publish(cm)
        if self.people_enabled:
            msg = PerceptionTargets()
            now_ns = self.node.get_clock().now().nanoseconds - int(self.age * 1e9)
            msg.header.stamp.sec, msg.header.stamp.nanosec = divmod(now_ns, 1000000000)
            msg.header.frame_id = 'camera_link'
            for identity, x, y in self.people:
                t = Target()
                t.type, t.track_id = 'person', identity
                roi = Roi()
                roi.type, roi.confidence = 'person', 0.95
                roi.rect.x_offset, roi.rect.y_offset = self.bbox_x, 100
                roi.rect.width, roi.rect.height = self.bbox_width, 300
                t.rois = [roi]
                t.attributes = [Attribute(type=k, value=float(v)) for k, v in
                    [('x_cm', x * 100), ('y_cm', y * 100), ('width_cm', 50), ('height_cm', 170)]]
                msg.targets.append(t)
            self.perception.publish(msg)

    def wait(self, seconds):
        time.sleep(seconds)
        assert self.process.poll() is None

    def until(self, predicate, timeout=3.0):
        end = time.monotonic() + timeout
        while not predicate() and time.monotonic() < end:
            self.wait(0.01)
        assert predicate()

    def enable(self, enabled=True):
        future = self.service.call_async(SetBool.Request(data=enabled))
        end = time.monotonic() + 3.0
        while not future.done() and time.monotonic() < end: time.sleep(0.01)
        assert future.done() and future.result().success

    def track(self):
        self.enable()
        for i in range(14):
            self.people = [(42, 2.4 + i * 0.03, 0.0)]
            self.wait(0.07)
        assert any('TRACKING' in s for s in self.status)

    def close(self):
        if self.process.poll() is None:
            self.enable(False)
            time.sleep(max(0.2, self.delay + 0.2, self.spin_delay + 0.2))
            self.process.send_signal(signal.SIGINT)
            try: self.process.wait(5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.running = False
        self.timer.cancel()
        self.executor.shutdown(timeout_sec=3.0)
        if self.server is not None: self.server.destroy()
        if self.spin_server is not None: self.spin_server.destroy()
        self.external_spin.destroy()
        self.external.destroy()
        self.node.destroy_node()
        rclpy.shutdown()
        self.log.close()


@pytest.fixture
def harness(tmp_path):
    instances = []
    def create(**kwargs):
        h = Harness(tmp_path, **kwargs)
        instances.append(h)
        return h
    yield create
    for h in instances: h.close()


def test_dry_run_geometry_rate_and_no_action_or_twist(harness):
    h = harness()
    h.wait(0.3)
    assert not h.candidates and not h.goals
    h.track()
    assert h.candidates and not h.goals and not h.cancels
    p = h.candidates[-1]
    assert p.header.frame_id == 'map'
    assert abs(p.pose.position.x - 1.0) < 0.05
    assert 4.6 < p.pose.position.y < 5.2
    q = p.pose.orientation
    assert abs(q.x*q.x + q.y*q.y + q.z*q.z + q.w*q.w - 1) < 0.001
    assert p.header.stamp.sec > 0
    endpoints = h.node.get_publisher_names_and_types_by_node('tros_person_following_node', '/follow')
    assert all('geometry_msgs/msg/Twist' not in types for _, types in endpoints)
    h.candidates.clear()
    for i in range(10):
        h.people = [(42, 3.0 + i * 0.12, 0.0)]
        h.wait(0.05)
    assert len(h.candidates) <= 2
    h.candidates.clear()
    h.people = [(42, 1.4, 0.0)]
    h.until(lambda: bool(h.status) and 'dist=1.60' in h.status[-1])
    h.candidates.clear()  # Discard already published far-goal transport samples.
    h.wait(0.4)
    assert not h.candidates
    for x in [1.8, 1.9, 1.95, 1.85]:
        h.people = [(42, x - 0.2, 0.0)]
        h.wait(0.1)
    assert not h.candidates


@pytest.mark.parametrize('fault', ['old_detection', 'nan_depth', 'no_detection', 'stale_tf',
                                 'stale_map', 'unknown', 'occupied', 'short', 'frame', 'rotated'])
def test_fail_closed_inputs(harness, fault):
    h = harness()
    h.track()
    assert h.candidates
    if fault == 'old_detection': h.age = 3.0
    elif fault == 'nan_depth': h.people = [(42, float('nan'), 0.0)]
    elif fault == 'no_detection': h.people_enabled = False
    elif fault == 'stale_tf': h.tf_enabled = False
    elif fault == 'stale_map': h.map_enabled = False
    else: h.bad_map = fault
    h.wait(2.2 if fault == 'stale_map' else 0.9)
    h.candidates.clear()
    h.wait(0.5)
    assert not h.candidates
    assert not h.goals and not h.cancels


def test_lost_original_id_relock(harness):
    h = harness()
    h.track()
    h.people = []
    h.wait(0.4)
    assert any('LOST' in s for s in h.status)
    count = len(h.candidates)
    h.people = [(42, 2.8, 0.0)]
    h.wait(0.6)
    assert 'TRACKING' in h.status[-1] and ':id=42' in h.status[-1]
    assert len(h.candidates) >= count


def test_lost_timeout_without_simulated_arrival(harness):
    h = harness()
    h.track()
    h.people = []
    h.wait(1.5)
    assert 'IDLE_SEARCHING' in h.status[-1]


def test_new_mot_id_requires_motion_before_relock(harness):
    h = harness()
    h.track()
    h.people = []
    h.wait(0.1)
    h.people = [(99, 2.8, 0.0)]
    h.wait(0.2)
    assert not any('TRACKING:id=99' in s for s in h.status)
    for i in range(6):
        h.people = [(99, 2.8 + i * 0.04, 0.0)]
        h.wait(0.06)
    h.until(lambda: 'TRACKING:id=99' in h.status[-1])


def test_server_unavailable_and_rejected(harness):
    h = harness(mode='nav2_action', server=False)
    h.track()
    assert not h.goals and any('unavailable' in s for s in h.diagnostics)


def test_rejected_goal(harness):
    h = harness(mode='nav2_action', reject=True)
    h.track()
    assert not h.goals and any('REJECTED' in s for s in h.diagnostics)


@pytest.mark.parametrize('delay', [0.0, 1.2])
def test_owned_cancel_preserves_external_goal(harness, delay):
    h = harness(mode='nav2_action', delay=delay)
    assert h.external.wait_for_server(timeout_sec=3.0)
    other = NavigateToPose.Goal()
    other.pose.header.frame_id = 'map'
    other.pose.pose.position.x = 99.0
    other.pose.pose.orientation.w = 1.0
    f = h.external.send_goal_async(other)
    end = time.monotonic() + 3.0
    while not f.done() and time.monotonic() < end: time.sleep(0.01)
    assert f.done() and f.result().accepted
    external_id = bytes(f.result().goal_id.uuid)
    h.track()
    h.enable(False)
    h.wait(1.2)
    assert h.cancels and external_id not in h.cancels
    assert not h.handles[0].is_cancel_requested
    count = len(h.goals)
    h.wait(0.4)
    assert len(h.goals) == count


@pytest.mark.parametrize('delay', [0.0, 1.2])
def test_shutdown_cancels_owned_goal_only(harness, delay):
    h = harness(mode='nav2_action', delay=delay)
    assert h.external.wait_for_server(timeout_sec=3.0)
    other = NavigateToPose.Goal()
    other.pose.header.frame_id = 'map'
    other.pose.pose.position.x = 99.0
    other.pose.pose.orientation.w = 1.0
    future = h.external.send_goal_async(other)
    end = time.monotonic() + 3
    while not future.done() and time.monotonic() < end: time.sleep(0.01)
    assert future.done() and future.result().accepted
    external_id = bytes(future.result().goal_id.uuid)
    h.track()
    assert any('SENT' in s for s in h.diagnostics)
    if delay:
        assert not any('ACCEPTED' in s for s in h.diagnostics)
    h.process.send_signal(signal.SIGINT)
    assert h.process.wait(5) == 0
    assert h.cancels and external_id not in h.cancels


@pytest.mark.parametrize('code', ['success', 'abort'])
def test_action_result_and_resend(harness, code):
    h = harness(mode='nav2_action')
    h.track()
    assert h.goals
    h.finish_code = code
    h.until(lambda: any('RESULT code=' in s for s in h.diagnostics))
    h.finish_code = None
    before = len(h.goals)
    h.people = [(42, 4.0, 0.0)]
    h.wait(0.7)
    assert len(h.goals) > before
