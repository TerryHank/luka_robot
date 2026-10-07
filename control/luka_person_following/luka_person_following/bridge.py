"""Adapt existing BPU/GUI observations; never perform a second inference."""
import copy
import json
import time
from urllib.request import urlopen

import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from rclpy.time import Time
from ai_msgs.msg import PerceptionTargets, Target, Roi, Attribute
from geometry_msgs.msg import PointStamped
from sensor_msgs.msg import CameraInfo
from std_msgs.msg import String
from std_srvs.srv import SetBool
from tf2_ros import Buffer, TransformListener
from tf2_geometry_msgs import do_transform_point
from .selection import selected_observation


class SelectedBridge(Node):
    def __init__(self):
        super().__init__('selected_bridge')
        self.url = self.declare_parameter('status_url', 'http://127.0.0.1:8098/api/people/follow-state').value
        self.auto_select_first_person = bool(self.declare_parameter('auto_select_first_person', True).value)
        self.pub = self.create_publisher(PerceptionTargets, '/luka/selected_seg_targets', 10)
        self.diag = self.create_publisher(String, '/luka_person_following/adapter_status', 10)
        self.tf = Buffer()
        self.listener = TransformListener(self.tf, self)
        self.optical_frame = None
        self.create_subscription(CameraInfo, '/camera/color/camera_info', self.camera_info, qos_profile_sensor_data)
        self.client = self.create_client(SetBool, '/luka_person_following/official/enable_follow')
        self.base_follow_client = self.create_client(SetBool, '/nx/follow_enable')
        self.create_service(SetBool, '/luka_person_following/set_enabled', self.set_enabled)
        self.desired = False
        self.applied = None
        self.pending = None
        self.base_pending = None
        self.base_applied = None
        self.last_id = None
        self.valid = False
        self.robot_tf_ready = False
        self.reason = 'starting'
        self.disarm_reason = None
        self.current_block_reason = None
        self.last_disarm_reason = None
        self.last_disarm_time = None
        self.last_valid_row = None
        self.last_valid_track_id = None
        self.last_valid_mono = None
        self.depth_invalid_grace_sec = float(self.declare_parameter('depth_invalid_grace_sec', .9).value)
        self.max_depth_jump_m = float(self.declare_parameter('max_depth_jump_m', .6).value)
        self.single_person_auto_relock = bool(self.declare_parameter('single_person_auto_relock', True).value)
        self.id_grace_timeout = float(self.declare_parameter('id_grace_timeout', .8).value)
        self.relock_max_time_gap = float(self.declare_parameter('relock_max_time_gap', 1.5).value)
        self.relock_max_position_delta = float(self.declare_parameter('relock_max_position_delta', .8).value)
        self.relock_max_depth_delta = float(self.declare_parameter('relock_max_depth_delta', .6).value)
        self.target_lost_timeout = float(self.declare_parameter('target_lost_timeout', 3.0).value)
        self.stop_while_relocking = bool(self.declare_parameter('stop_while_relocking', True).value)
        self.enable_debug_log = bool(self.declare_parameter('enable_debug_log', True).value)
        self.follow_state = 'IDLE'
        self.grace_started_mono = None
        self.last_target_xyz = None
        self.create_timer(.125, self.poll)

    def camera_info(self, msg):
        self.optical_frame = msg.header.frame_id

    def _single_person_state(self, state):
        return (self.single_person_auto_relock and
                len([item for item in state.get('tracks', [])
                     if item.get('class', 'person') == 'person']) == 1)

    def _continuous_target(self, row, now_mono):
        if self.last_valid_row is None or self.last_valid_mono is None:
            return True
        dt = now_mono - self.last_valid_mono
        # After the configured LOST timeout there is no useful old trajectory
        # left to compare against; in single-person mode establish a fresh
        # continuity anchor instead of rejecting the same visible person
        # forever on every subsequent frame.
        if dt > self.target_lost_timeout:
            return True
        old_xyz = (self.last_valid_row.get('depth_diagnostic') or {}).get('position_optical_m')
        new_xyz = (row.get('depth_diagnostic') or {}).get('position_optical_m')
        if not (isinstance(old_xyz, list) and len(old_xyz) == 3 and
                isinstance(new_xyz, list) and len(new_xyz) == 3):
            return False
        position_delta = sum((float(new_xyz[i]) - float(old_xyz[i])) ** 2 for i in range(3)) ** 0.5
        depth_delta = abs(float(new_xyz[2]) - float(old_xyz[2]))
        return (dt <= self.relock_max_time_gap and
                position_delta <= self.relock_max_position_delta and
                depth_delta <= self.relock_max_depth_delta)

    def set_enabled(self, request, response):
        recent_valid = (self.last_valid_row is not None and
                         self.last_valid_mono is not None and
                         time.monotonic() - self.last_valid_mono <= .9)
        if request.data and (not (self.valid or recent_valid) or not self.robot_tf_ready or
                             not self.client.service_is_ready() or
                             not self.base_follow_client.service_is_ready()):
            response.success = False
            response.message = 'Cannot enable: ' + (self.reason if not self.valid else 'map/base/camera TF or controller unavailable')
        else:
            self.desired = request.data
            self.current_block_reason = None if request.data else 'manual_disable'
            self.disarm_reason = self.current_block_reason
            response.success = True
            response.message = 'Enable requested' if request.data else 'Disable requested'
        return response

    def sync_enable(self):
        if self.pending is not None:
            if not self.pending.done():
                return
            try:
                response = self.pending.result()
                self.applied = self.pending_value if response.success else None
            except Exception:
                self.applied = None
            self.pending = None
        if self.base_pending is not None:
            if not self.base_pending.done():
                return
            try:
                response = self.base_pending.result()
                self.base_applied = self.base_pending_value if response.success else None
            except Exception:
                self.base_applied = None
            self.base_pending = None
        if self.applied != self.desired and self.client.service_is_ready():
            req = SetBool.Request()
            req.data = self.desired
            self.pending_value = self.desired
            self.pending = self.client.call_async(req)
            return
        if (self.base_applied != self.desired and
                self.base_follow_client.service_is_ready()):
            req = SetBool.Request()
            req.data = self.desired
            self.base_pending_value = self.desired
            self.base_pending = self.base_follow_client.call_async(req)

    def poll(self):
        msg = PerceptionTargets()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = 'camera_link'
        row = None
        auto_single_person = False
        try:
            started = time.monotonic()
            with urlopen(self.url, timeout=.75) as response:
                state = json.load(response)
            row, self.reason = selected_observation(state, time.monotonic() - started)
            held = False
            state_selected_id = state.get('selected_track_id')
            auto_single_person = self._single_person_state(state)
            if (row is None and (self.reason in ("invalid_seg_depth", "depth_jump_rejected", "stale_frame",
                                    "official_target_filter", "selected_missing",
                                    "selected_ambiguous_or_weak") or
                         self.reason.startswith("source_or_tf_unavailable"))
                    and self.last_valid_row is not None
                    and (state_selected_id == self.last_valid_track_id or auto_single_person)
                    and self.last_valid_mono is not None
                    and time.monotonic() - self.last_valid_mono <= self.depth_invalid_grace_sec):
                row = copy.deepcopy(self.last_valid_row)
                self.reason = 'selected_seg_depth_held'
                held = True
            if row is not None and not held and self.last_valid_row is not None:
                if (auto_single_person and self.last_valid_track_id is not None and
                        int(row['track_id']) != int(self.last_valid_track_id) and
                        not self._continuous_target(row, time.monotonic())):
                    row = None
                    self.reason = 'relock_rejected'
                if row is not None:
                    old_geo = self.last_valid_row.get('depth_diagnostic') or {}
                    new_geo = row.get('depth_diagnostic') or {}
                    old_xyz, new_xyz = old_geo.get('position_optical_m'), new_geo.get('position_optical_m')
                    if (isinstance(old_xyz, list) and len(old_xyz) == 3 and
                            isinstance(new_xyz, list) and len(new_xyz) == 3 and
                            abs(float(new_xyz[2]) - float(old_xyz[2])) > self.max_depth_jump_m):
                        row = None
                        self.reason = 'depth_jump_rejected'
                        if ((state_selected_id == self.last_valid_track_id or auto_single_person) and
                                self.last_valid_mono is not None and
                                time.monotonic() - self.last_valid_mono <= self.depth_invalid_grace_sec):
                            row = copy.deepcopy(self.last_valid_row)
                            self.reason = 'selected_seg_depth_held'
                            held = True
            if row is not None:
                point = PointStamped()
                point.header.frame_id = self.optical_frame or ''
                xyz = row['depth_diagnostic']['position_optical_m']
                point.point.x, point.point.y, point.point.z = map(float, xyz)
                transform = self.tf.lookup_transform('camera_link', point.header.frame_id, Time())
                p = do_transform_point(point, transform).point
                if not (.1 <= p.x <= 4.0 and -3.0 <= p.y <= 3.0):
                    raise ValueError('Selected point outside official following range')
                if not held:
                    self.last_valid_row = copy.deepcopy(row)
                    self.last_valid_track_id = int(row['track_id'])
                    self.last_valid_mono = time.monotonic()
                target = Target()
                target.type, target.track_id = 'person', int(row['track_id'])
                roi = Roi()
                roi.type, roi.confidence = 'person', float(row['confidence'])
                x1, y1, x2, y2 = map(int, row['bbox'])
                roi.rect.x_offset, roi.rect.y_offset = x1, y1
                roi.rect.width, roi.rect.height = x2-x1, y2-y1
                target.rois = [roi]
                geo = row['depth_diagnostic']
                for key, value in [('x_cm', p.x*100), ('y_cm', p.y*100),
                                   ('width_cm', geo['width_m']*100), ('height_cm', geo['height_m']*100)]:
                    attr = Attribute()
                    attr.type, attr.value, attr.confidence = key, float(value), roi.confidence
                    target.attributes.append(attr)
                # The point is computed from the registered RGB-D frame, not the polling time.
                msg.header.stamp = Time(seconds=float(state['frame_at'])).to_msg()
                msg.targets = [target]
        except Exception as exc:
            row = None
            self.reason = 'source_or_tf_unavailable: ' + str(exc)[:160]
        self.valid = row is not None and bool(msg.targets)
        self.robot_tf_ready = (self.tf.can_transform('map', 'base_footprint', Time())
                               and self.tf.can_transform('map', 'camera_link', Time()))
        current_id = row['track_id'] if self.valid else None
        disarm_reason = None
        transient_reason = (self.reason in ('invalid_seg_depth', 'depth_jump_rejected',
                                            'stale_frame', 'selected_missing',
                                            'selected_ambiguous_or_weak',
                                            'official_target_filter', 'relock_rejected',
                                            'selected_seg_depth_held') or
                            self.reason.startswith('source_or_tf_unavailable'))
        if not self.robot_tf_ready:
            disarm_reason = 'tf_unavailable'
        elif self.valid:
            if (self.last_id is not None and current_id != self.last_id and
                    auto_single_person and self._continuous_target(row, time.monotonic()) and
                    self.enable_debug_log):
                self.get_logger().warning(
                    f'Target relocked: track_id {self.last_id} -> {current_id}; '
                    'reason=single_person_continuity')
            self.follow_state = 'TRACKING'
            self.grace_started_mono = None
        elif transient_reason and self.desired:
            now_mono = time.monotonic()
            age = (now_mono - self.last_valid_mono
                   if self.last_valid_mono is not None else float('inf'))
            if self.grace_started_mono is None:
                self.grace_started_mono = now_mono
            if age <= self.id_grace_timeout:
                self.follow_state = 'GRACE'
            elif age <= self.target_lost_timeout:
                self.follow_state = 'RELOCK'
            else:
                self.follow_state = 'LOST'
            # A transient perception failure stops the published target frame,
            # but must not turn off the user's follow request.
            disarm_reason = None
        elif not self.valid:
            disarm_reason = self.reason
        if disarm_reason is not None:
            self.desired = False
            self.current_block_reason = disarm_reason
            self.disarm_reason = disarm_reason
            if disarm_reason != self.last_disarm_reason:
                self.last_disarm_reason = disarm_reason
                self.last_disarm_time = time.time()
        elif self.current_block_reason != 'manual_disable':
            self.current_block_reason = None
            self.disarm_reason = None
        self.last_id = current_id
        self.sync_enable()
        # Finish cancellation before delivering a changed ID or empty frame to
        # the upstream recovery state machine.
        if self.desired or self.applied is not True:
            self.pub.publish(msg)
        status = dict(valid=self.valid, reason=self.reason, selected_track_id=current_id,
                      enabled_requested=self.desired, enabled_applied=self.applied,
                      base_follow_enabled=self.base_applied,
                      robot_tf_ready=self.robot_tf_ready,
                      depth_method='seg_valid_trimmed_mean', optical_frame=self.optical_frame,
                      disarm_reason=self.current_block_reason,
                      current_block_reason=self.current_block_reason,
                      follow_state=self.follow_state,
                      last_disarm_reason=self.last_disarm_reason,
                      last_disarm_time=self.last_disarm_time,
                      depth_hold=(self.reason == 'selected_seg_depth_held'))
        self.diag.publish(String(data=json.dumps(status)))


def main():
    rclpy.init()
    node = SelectedBridge()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()
