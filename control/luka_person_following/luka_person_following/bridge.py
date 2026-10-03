"""Adapt existing BPU/GUI observations; never perform a second inference."""
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
        self.create_service(SetBool, '/luka_person_following/set_enabled', self.set_enabled)
        self.desired = False
        self.applied = None
        self.pending = None
        self.last_id = None
        self.valid = False
        self.robot_tf_ready = False
        self.reason = 'starting'
        self.disarm_reason = None
        self.create_timer(.125, self.poll)

    def camera_info(self, msg):
        self.optical_frame = msg.header.frame_id

    def set_enabled(self, request, response):
        if request.data and (not self.valid or not self.robot_tf_ready or not self.client.service_is_ready()):
            response.success = False
            response.message = 'Cannot enable: ' + (self.reason if not self.valid else 'map/base/camera TF or controller unavailable')
        else:
            self.desired = request.data
            self.disarm_reason = None if request.data else 'manual_disable'
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
        if self.applied != self.desired and self.client.service_is_ready():
            req = SetBool.Request()
            req.data = self.desired
            self.pending_value = self.desired
            self.pending = self.client.call_async(req)

    def poll(self):
        msg = PerceptionTargets()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = 'camera_link'
        row = None
        auto_single_person = False
        try:
            started = time.monotonic()
            with urlopen(self.url, timeout=.25) as response:
                state = json.load(response)
            row, self.reason = selected_observation(state, time.monotonic() - started)
            auto_single_person = (self.auto_select_first_person and
                                  len([item for item in state.get('tracks', [])
                                       if item.get('class', 'person') == 'person']) == 1)
            if row is not None:
                point = PointStamped()
                point.header.frame_id = self.optical_frame or ''
                xyz = row['depth_diagnostic']['position_optical_m']
                point.point.x, point.point.y, point.point.z = map(float, xyz)
                transform = self.tf.lookup_transform('camera_link', point.header.frame_id, Time())
                p = do_transform_point(point, transform).point
                if not (.1 <= p.x <= 4.0 and -3.0 <= p.y <= 3.0):
                    raise ValueError('Selected point outside official following range')
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
        if not self.valid:
            # Preserve the upstream validity reason (stale_frame, unselected,
            # invalid_seg_depth, selected_missing, ...).
            disarm_reason = self.reason
        elif not self.robot_tf_ready:
            disarm_reason = 'tf_unavailable'
        elif (self.last_id is not None and current_id != self.last_id
              and not auto_single_person):
            disarm_reason = 'track_id_changed'
        if disarm_reason is not None:
            self.desired = False
            self.disarm_reason = disarm_reason
        self.last_id = current_id
        self.sync_enable()
        # Finish cancellation before delivering a changed ID or empty frame to
        # the upstream recovery state machine.
        if self.desired or self.applied is not True:
            self.pub.publish(msg)
        status = dict(valid=self.valid, reason=self.reason, selected_track_id=current_id,
                      enabled_requested=self.desired, enabled_applied=self.applied,
                      robot_tf_ready=self.robot_tf_ready,
                      depth_method='seg_valid_trimmed_mean', optical_frame=self.optical_frame,
                      disarm_reason=self.disarm_reason)
        self.diag.publish(String(data=json.dumps(status)))


def main():
    rclpy.init()
    node = SelectedBridge()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()
