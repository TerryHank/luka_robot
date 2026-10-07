"""Isolated ROS domain, synthetic TF/RGB-D, fake Nav2. No robot endpoints."""
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import rclpy
from rclpy.node import Node
from rclpy.executors import MultiThreadedExecutor
from rclpy.action import ActionServer, GoalResponse, CancelResponse
from rclpy.action import get_action_client_names_and_types_by_node
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CameraInfo
from geometry_msgs.msg import TransformStamped, Twist
from nav2_msgs.action import NavigateToPose
from nav_msgs.msg import OccupancyGrid
from std_msgs.msg import String
from std_srvs.srv import SetBool
from ai_msgs.msg import PerceptionTargets
from tf2_ros import StaticTransformBroadcaster

assert os.environ.get('ROS_DOMAIN_ID') == '88', 'Test must be isolated in domain 88'
ROOT = Path('/home/sunrise/luka_ws/evaluator/official_follow_acceptance_20261004')
ROOT.mkdir(exist_ok=True)
state = dict(active=True, loading=False, camera_age=.05, selected_track_id=None,
             frame_width=640, frame_height=480, tracks=[])
row = dict(track_id=12, confidence=.95, bbox=[250,60,390,450], visible=True,
           observation_strength='strong', association_ambiguous=False, depth_valid=True,
           depth_diagnostic=dict(method='seg_valid_arithmetic_mean',
               position_optical_m=[0,0,3], width_m=.6, height_m=1.7))


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        data = json.dumps(dict(state, frame_at=time.time()-.05)).encode()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_):
        pass


class Fixture(Node):
    def __init__(self):
        super().__init__('static_follow_fixture')
        self.goals, self.cancels, self.targets, self.statuses, self.vels = [], [], [], [], []
        self.create_subscription(PerceptionTargets, '/luka/selected_seg_targets', self.targets.append, 10)
        self.create_subscription(String, '/luka_person_following/adapter_status', lambda m: self.statuses.append(json.loads(m.data)), 10)
        self.create_subscription(Twist, '/luka_follow_dryrun/cmd_vel', self.vels.append, 10)
        self.camera = self.create_publisher(CameraInfo, '/camera/color/camera_info', qos_profile_sensor_data)
        self.costmap = self.create_publisher(OccupancyGrid, '/global_costmap/costmap', 10)
        self.create_timer(.1, self.publish_camera)
        self.broadcaster = StaticTransformBroadcaster(self)
        transforms = []
        for parent, child, rotation in [('map','base_link',(0,0,0,1)),
                                       ('camera_link','camera_color_optical_frame',(-.5,.5,-.5,.5))]:
            tf = TransformStamped()
            tf.header.frame_id, tf.child_frame_id = parent, child
            tf.header.stamp = self.get_clock().now().to_msg()
            tf.transform.rotation.x, tf.transform.rotation.y, tf.transform.rotation.z, tf.transform.rotation.w = map(float, rotation)
            transforms.append(tf)
        self.broadcaster.sendTransform(transforms)
        self.server = ActionServer(self, NavigateToPose, '/luka_follow_dryrun/navigate_to_pose',
                                   execute_callback=self.execute, goal_callback=self.goal,
                                   cancel_callback=self.cancel, callback_group=ReentrantCallbackGroup())
        self.client = self.create_client(SetBool, '/luka_person_following/set_enabled')

    def publish_camera(self):
        msg = CameraInfo()
        msg.header.frame_id = 'camera_color_optical_frame'
        msg.width, msg.height = 640, 480
        self.camera.publish(msg)
        grid = OccupancyGrid()
        grid.header.frame_id = 'map'
        grid.header.stamp = self.get_clock().now().to_msg()
        grid.info.resolution = .1
        grid.info.width, grid.info.height = 100, 100
        grid.info.origin.position.x, grid.info.origin.position.y = -5.0, -5.0
        grid.info.origin.orientation.w = 1.0
        grid.data = [0]*10000
        self.costmap.publish(grid)

    def goal(self, request):
        p = request.pose.pose.position
        self.goals.append(dict(x=p.x,y=p.y,frame=request.pose.header.frame_id))
        return GoalResponse.ACCEPT

    def cancel(self, handle):
        self.cancels.append(time.monotonic())
        return CancelResponse.ACCEPT

    def execute(self, handle):
        while rclpy.ok() and not handle.is_cancel_requested:
            time.sleep(.05)
        if handle.is_cancel_requested:
            handle.canceled()
        else:
            handle.abort()
        return NavigateToPose.Result()

    def enable(self, value):
        assert self.client.wait_for_service(timeout_sec=4)
        req = SetBool.Request()
        req.data = value
        future = self.client.call_async(req)
        wait(lambda: future.done(), 4)
        return future.result()


def wait(predicate, seconds=8):
    deadline = time.monotonic()+seconds
    while time.monotonic()<deadline:
        if predicate():
            return
        time.sleep(.05)
    raise AssertionError('Timed out waiting for ' + str(predicate))


http = ThreadingHTTPServer(('127.0.0.1',18098),Handler)
threading.Thread(target=http.serve_forever,daemon=True).start()
rclpy.init()
node = Fixture()
executor = MultiThreadedExecutor(num_threads=6)
executor.add_node(node)
threading.Thread(target=executor.spin,daemon=True).start()
log = (ROOT/'launch.log').open('w')
process = subprocess.Popen(['ros2','launch','luka_person_following','selected_follow.launch.py',
                            'dry_run:=true',
                            'status_url:=http://127.0.0.1:18098/state'],
                           stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
results = {}
try:
    wait(lambda: node.statuses and node.statuses[-1]['enabled_applied'] is False)
    results['action_clients'] = get_action_client_names_and_types_by_node(
        node, 'tros_person_following_node', '/luka_person_following/official')
    assert not node.enable(True).success
    assert not node.goals
    results['unselected_enable_rejected'] = True
    state.update(selected_track_id=12, tracks=[row,dict(row,track_id=99,confidence=.99)])
    wait(lambda: node.targets and len(node.targets[-1].targets)==1)
    target = node.targets[-1].targets[0]
    assert target.track_id == 12
    attributes = {a.type:a.value for a in target.attributes}
    assert abs(attributes['x_cm']-300)<.001 and abs(attributes['y_cm'])<.001
    results['selected_only_and_optical_axes'] = attributes
    assert node.enable(True).success
    # The upstream controller selects a moving person; move only the synthetic point.
    start = time.monotonic()
    while time.monotonic()-start<3:
        row['depth_diagnostic']['position_optical_m'][2] = 3+min(.8,(time.monotonic()-start)*.4)
        time.sleep(.08)
    wait(lambda: node.goals, 8)
    assert all(g['frame']=='map' and 3<g['x']<=3.81 and abs(g['y'])<.001 for g in node.goals)
    results['official_nav2_goals'] = list(node.goals)
    row['depth_diagnostic']['position_optical_m'][2] = 1.5
    wait(lambda: bool(node.cancels))
    before = len(node.goals)
    time.sleep(.5)
    assert len(node.goals)==before
    assert node.vels and node.vels[-1].linear.x==0 and node.vels[-1].angular.z==0
    results['below_1_8m_cancels_and_stops'] = True
    row['depth_diagnostic']['position_optical_m'][2] = 3.7
    wait(lambda: len(node.goals)>before)
    cancel_before = len(node.cancels)
    # Depth loss must disarm and cancel the fake Nav2 goal, never choose track 99.
    row['depth_valid'] = False
    wait(lambda: node.statuses[-1]['enabled_applied'] is False)
    wait(lambda: len(node.cancels)>cancel_before)
    assert not node.targets[-1].targets
    results['invalid_depth_disarms_and_cancels'] = True
    before = len(node.goals)
    row['depth_valid'] = True
    time.sleep(.6)
    assert len(node.goals)==before
    assert node.statuses[-1]['enabled_requested'] is False
    results['recovery_requires_explicit_reenable'] = True
    # Switch a selected target while enabled: disarm rather than carrying a goal across IDs.
    assert node.enable(True).success
    wait(lambda: node.statuses[-1]['enabled_applied'] is True)
    state['selected_track_id'] = 99
    wait(lambda: node.statuses[-1]['enabled_applied'] is False)
    assert node.targets[-1].targets[0].track_id==99
    results['selection_change_disarms'] = True
    state['camera_age'] = .9
    wait(lambda: node.statuses[-1]['reason']=='stale_frame')
    assert not node.targets[-1].targets
    results['stale_frame_empty_targets'] = True
    # No publisher is allowed on the real robot velocity/action endpoints in this domain.
    topic_types = dict(node.get_topic_names_and_types())
    assert '/cmd_vel' not in topic_types
    assert '/navigate_to_pose/_action/feedback' not in topic_types
    results['real_motion_endpoints_absent'] = True
    results['synthetic_tf_only'] = True
    results['pass'] = True
finally:
    os.killpg(process.pid,signal.SIGINT)
    try:
        process.wait(timeout=6)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid,signal.SIGTERM)
        process.wait(timeout=5)
    log.close()
    http.shutdown()
    executor.shutdown(timeout_sec=2)
    node.destroy_node()
    rclpy.shutdown()
    (ROOT/'results.json').write_text(json.dumps(results,indent=2))
print(json.dumps(results,indent=2))

