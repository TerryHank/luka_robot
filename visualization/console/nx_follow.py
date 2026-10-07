"""Conservative first-pass person following. All wheel commands have a base watchdog."""
import json
import math
import os
import threading
import time
from urllib.request import urlopen

from geometry_msgs.msg import Twist
from sensor_msgs.msg import Joy, LaserScan
from std_srvs.srv import Empty, SetBool
from rclpy.qos import qos_profile_sensor_data

from person_range_gate import PersonRangeGate
from nx_follow_map import MapFollowEstimate
from nx_follow_detour import FollowDetourManager
from web_teleop_safety import follow_motion_blocked


def project_target(previous, track_id, stamp, center):
    """Short, bounded image-plane lead; never used as identity or distance."""
    if (type(track_id) is not int or not isinstance(stamp, (int, float)) or
            not isinstance(center, (int, float)) or not math.isfinite(stamp) or
            not math.isfinite(center) or not 0. <= center <= 1.):
        return None, None
    velocity = 0.
    if previous is not None and previous[0] == track_id:
        dt = stamp - previous[1]
        if .05 <= dt <= .8:
            measured = max(-.7, min(.7, (center-previous[2])/dt))
            velocity = .55*previous[3] + .45*measured
    return (track_id, stamp, center, velocity), max(.03, min(.97, center+velocity*.22))


def decide(people, camera_age, front_clearance, scans_fresh, allow_anonymous=False,
           rear_clearance=None, rear_scans_fresh=False, predicted_center=None):
    """Return (forward m/s, yaw rad/s, reason); fail closed on uncertain data."""
    if not isinstance(people, dict) or people.get('active') is not True or people.get('loading') or people.get('error'):
        return 0., 0., '人体识别未就绪'
    if not isinstance(camera_age, (int, float)) or not math.isfinite(camera_age) or camera_age > .9:
        return 0., 0., '相机画面过期'
    target = people.get('target_session') or {}
    if not (target.get('active') and target.get('visible') and
            ((target.get('face_verified') and target.get('profile_id')) or allow_anonymous)):
        return 0., 0., '目标未完成身份核对或暂时丢失'
    if people.get('enrollment', {}).get('active'):
        return 0., 0., '正在录入人脸'
    tracks = people.get('tracks') or []
    selected = [t for t in tracks if t.get('track_id') == target.get('track_id')]
    if len(selected) != 1 or selected[0].get('selected') is False:
        return 0., 0., '目标检测不唯一'
    person = selected[0]
    if allow_anonymous and not target.get('face_verified'):
        first, strong = person.get('first_seen'), person.get('last_strong_seen')
        if (not isinstance(first, (int, float)) or not isinstance(strong, (int, float))
                or strong - first < .25):
            return 0., 0., '等待当前人体连续稳定入镜'
    if person.get('association_ambiguous') or person.get('observation_strength') not in ('strong', 'strong_detection', 'stable_moderate_observation'):
        return 0., 0., '多人关联或人体检测不确定'
    width = people.get('frame_width')
    box = person.get('bbox')
    if not isinstance(width, (int, float)) or width <= 0 or not isinstance(box, list) or len(box) != 4 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in box):
        return 0., 0., '目标框无效'
    center = (box[0] + box[2]) / (2 * width)
    for other in tracks:
        if other is person or not isinstance(other.get('bbox'), list):
            continue
        b = other['bbox']
        if len(b) == 4 and min(box[2], b[2]) > max(box[0], b[0]) and min(box[3], b[3]) > max(box[1], b[1]):
            return 0., 0., '多人框重叠，暂停核对'
    if not scans_fresh or not isinstance(front_clearance, (int, float)) or not math.isfinite(front_clearance):
        return 0., 0., '雷达数据过期或前方未知'
    steering_center = predicted_center if isinstance(predicted_center, (int, float)) and math.isfinite(predicted_center) else center
    steering_center = max(.03, min(.97, steering_center))
    offset = steering_center - .5
    distance = person.get('distance_m')
    depth_ready = (people.get('metric_depth_available') and person.get('depth_valid') is True and
                   isinstance(distance, (int, float)) and math.isfinite(distance) and .6 < distance < 4.0)
    if depth_ready and distance < 1.20:
        if not rear_scans_fresh or not isinstance(rear_clearance, (int, float)) or not math.isfinite(rear_clearance):
            return 0., 0., '后方雷达数据过期，不能退让'
        if rear_clearance <= .75:
            return 0., 0., '后方空间不足，不能退让'
        reverse = min(.12, (1.35-distance)*.35,
                      (rear_clearance-.75)*.35)
        return -max(0., reverse), 0., '目标过近，低速退让'
    # This S100 stereo calibration keeps the full left-camera view for person
    # detection, but live depth is reliable only from about x=240/640 onward.
    # Turn in place until the *same* body is inside the measured overlap.
    # The caller and base independently check the turn sweep.
    if not .43 <= center <= .87:
        if front_clearance < .45:
            return 0., 0., '前方障碍物过近'
        if .06 <= center <= .94:
            direction = 1. if center < .43 else -1.
            # Camera updates are slower than the base loop, so keep this
            # bounded while avoiding an unnecessarily long turn at the edge.
            yaw_to_overlap = direction * max(.30, min(.45, abs(offset)*1.35))
            return 0., yaw_to_overlap, '目标偏侧，原地转向重新测距'
        return 0., 0., '目标几乎离开画面'
    if not people.get('metric_depth_available') or person.get('depth_valid') is not True:
        return 0., 0., '双目距离无效'
    if not depth_ready:
        return 0., 0., '目标距离超出可靠范围'
    if front_clearance < .75:
        return 0., 0., '前方障碍物过近'
    yaw = max(-.50, min(.50, -offset * 1.50)) if abs(offset) > .06 else 0.
    if distance <= 1.45:
        return 0., 0., '已保持跟随距离'
    # Walk at a useful pace only when both the person and the radar corridor
    # are clear. The last 0.75 m of measured clearance remains a hard stop.
    forward = min(.40, max(0., (distance - 1.45) * .80),
                  max(0., (front_clearance - .75) * .55))
    if abs(offset) > .22:
        forward = min(forward, .10)
    if forward < .02:
        return 0., 0., '前方空间不足，停车等待'
    return forward, yaw, '低速跟随'


class FollowController:
    def __init__(self, node):
        self.node = node
        self.lock = threading.RLock()
        self.enabled = False
        self.mode = 'profile'
        self.command_epoch = 0
        self.reason = '未启动'
        self.people = None
        self.people_at = 0.
        self.last_frame_at = None
        self.same_frame_since = 0.
        self.scans = {}
        self.rear_scans = {}
        self.scan_points = {}
        self.motion_state = None
        self.predicted_center = None
        self.command = (0., 0.)
        self.profile_id = None
        self.track_id = None
        self.recovery_candidate_id = None
        self.recovery_candidate_since = None
        self.nav_mode = os.getenv('NX_FOLLOW_NAV_MODE', '0') == '1'
        self.hybrid_mode = os.getenv('NX_FOLLOW_HYBRID', '0') == '1'
        self.range_gate = PersonRangeGate(single_chest=self.nav_mode)
        # Continuous visual motion still uses the stricter body-layer check
        # before an observation can seed a map detour or stale-depth hint.
        self.map_estimator = MapFollowEstimate(require_chest=self.nav_mode or self.hybrid_mode)
        self.map_last_frame = None
        self.nomotion_at = 0.
        self.nomotion_future = None
        self.blocked_since = None
        self.detour = FollowDetourManager(self, node)
        self.detour_enabled = os.getenv('NX_FOLLOW_NAV_DETOUR', '0') == '1'
        # Legacy dashboard follow is kept off the official follow output.
        # The official selected-follow node is the sole /nx/follow_safe publisher.
        self.pub = node.create_publisher(Twist, '/nx/dashboard_follow_safe', 10)
        self.gate = node.create_client(SetBool, '/nx/follow_enable')
        for topic in ('/scan', '/scan_low_filtered'):
            node.create_subscription(LaserScan, topic, lambda msg, name=topic: self.on_scan(name, msg), qos_profile_sensor_data)
        node.create_subscription(Joy, '/joy', self.on_joy, qos_profile_sensor_data)
        node.create_timer(.1, self.tick)
        threading.Thread(target=self.poll_people, daemon=True).start()
        threading.Thread(target=self.poll_map_pose, daemon=True).start()

    def poll_map_pose(self):
        """Resolve image-time map pose away from the wheel-command loop."""
        while True:
            with self.lock:
                people = self.people
                frame = (people or {}).get('frame_at')
                target = (people or {}).get('target_session') or {}
                enabled = self.enabled
            if (enabled and not self.detour.active and
                    not self.node.relocalization.running and
                    time.monotonic()-self.nomotion_at >= .6 and
                    (self.nomotion_future is None or self.nomotion_future.done()) and
                    self.node.relocalization.update_client.service_is_ready()):
                self.nomotion_at = time.monotonic()
                self.nomotion_future = self.node.relocalization.update_client.call_async(
                    Empty.Request())
            if (enabled and isinstance(frame, (int, float)) and frame != self.map_last_frame and
                    target.get('active') and target.get('visible')):
                try:
                    context = self.node.object_pose_context.snapshot(frame)
                    with self.lock:
                        if (self.people or {}).get('frame_at') == frame:
                            self.map_estimator.observe(people, context)
                            self.map_last_frame = frame
                except Exception:
                    with self.lock:
                        self.map_estimator.clear('地图位姿不可用')
                        self.map_last_frame = frame
            time.sleep(.12)

    def on_scan(self, name, msg):
        values = []
        rear_values = []
        # Verified static TF: laser=(x -0.065, yaw 0), laser_low=(x 0.281,
        # y 0.005, yaw +89.94 deg) in base_link. Evaluate a base-frame
        # corridor; angle zero in the low scanner points to the robot's left.
        # S100's measured body half-width is 0.19 m. A 0.32 m half-corridor
        # leaves 0.13 m side clearance without treating furniture 0.35 m to
        # the side as a head-on obstacle. The 0.75 m forward stop stays intact.
        origin_x, origin_y, yaw = (-.065, 0., 0.) if name == '/scan' else (.281, .005, math.pi/2)
        valid_any = False
        rear_sector_covered = False
        nearby = []
        for index, value in enumerate(msg.ranges):
            angle = msg.angle_min + index * msg.angle_increment + yaw
            if math.cos(angle) < -.8:
                rear_sector_covered = True
            if not (math.isfinite(value) and max(.16, msg.range_min) < value < msg.range_max):
                continue
            valid_any = True
            x = origin_x + value * math.cos(angle)
            y = origin_y + value * math.sin(angle)
            if x*x+y*y < 1.44:
                nearby.append((x,y))
            if x > .15 and abs(y) < .32:
                values.append(x)
            if x < -.15 and abs(y) < .32:
                rear_values.append(-x)
        with self.lock:
            now = time.monotonic()
            self.scans[name] = (now, min(values) if values else float(msg.range_max) if valid_any else None)
            self.rear_scans[name] = (now, min(rear_values) if rear_values else
                                     float(msg.range_max) if rear_sector_covered and valid_any else None)
            self.scan_points[name] = nearby

    def on_joy(self, msg):
        if len(msg.buttons) > 4 and msg.buttons[4]:
            self.stop('手柄已接管')

    def poll_people(self):
        while True:
            try:
                with urlopen('http://127.0.0.1:8098/api/people/follow-state', timeout=.5) as response:
                    people = json.load(response)
                now = time.monotonic()
                with self.lock:
                    if people.get('frame_at') != self.last_frame_at:
                        self.last_frame_at = people.get('frame_at')
                        self.same_frame_since = now
                        target = people.get('target_session') or {}
                        selected = [row for row in people.get('tracks') or []
                                    if row.get('track_id') == target.get('track_id') and
                                    row.get('visible') is True and not row.get('association_ambiguous')]
                        if target.get('active') and len(selected) == 1:
                            box = selected[0].get('bbox')
                            width = people.get('frame_width')
                            center = ((box[0]+box[2])/(2*width) if isinstance(box, list) and
                                      len(box) == 4 and all(isinstance(v, (int,float)) and math.isfinite(v) for v in box) and
                                      isinstance(width, (int,float)) and math.isfinite(width) and width > 0 else None)
                            self.motion_state, self.predicted_center = project_target(
                                self.motion_state, target.get('track_id'), people.get('frame_at'), center)
                        else:
                            self.motion_state, self.predicted_center = None, None
                    self.people = self.range_gate.protect(people, allow_anonymous=self.mode == 'track')
                    self.people_at = now
            except Exception:
                pass
            time.sleep(.15)

    def snapshot(self):
        with self.lock:
            people = self.people or {}
            age = people.get('camera_age')
            age = age + time.monotonic()-self.people_at if isinstance(age, (int,float)) else None
            clearance, fresh = self.scan_state()
            rear_clearance, rear_fresh = self.rear_scan_state()
            _, _, ready_reason = decide(people, age, clearance, fresh,
                                        allow_anonymous=self.mode == 'track',
                                        rear_clearance=rear_clearance,
                                        rear_scans_fresh=rear_fresh,
                                        predicted_center=self.predicted_center)
            options = dict(profiles=[dict(id=p.get('id'), name=p.get('name'))
                                     for p in people.get('profiles') or []],
                           selected_track_id=people.get('selected_track_id'),
                           selected_track=next((dict(track_id=t.get('track_id'),
                                                     identity_name=(t.get('identity') or {}).get('name'),
                                                     visible=t.get('visible'),
                                                     observation_strength=t.get('observation_strength'))
                                                for t in people.get('tracks') or []
                                                if t.get('track_id') == people.get('selected_track_id')), None))
            return dict(enabled=self.enabled, reason=self.reason, forward_m_s=round(self.command[0], 3),
                        mode=self.mode,
                        options=options,
                        yaw_rad_s=round(self.command[1], 3), target_profile_id=self.profile_id,
                        target_track_id=self.track_id, person_age_s=round(time.monotonic()-self.people_at, 2) if self.people_at else None,
                        scan_ages_s={key:round(time.monotonic()-row[0], 2) for key,row in self.scans.items()},
                        ready=ready_reason in ('低速跟随','已保持跟随距离','目标偏侧，原地转向重新测距','目标过近，低速退让'),
                        ready_reason=ready_reason,
                        range_guard_reason=self.range_gate.reason,
                        front_clearance_m=round(clearance,2) if clearance is not None else None,
                        rear_clearance_m=round(rear_clearance,2) if rear_clearance is not None else None,
                        map_assist=self.map_estimator.status(),
                        detour=dict(enabled=self.detour_enabled,
                                    active=self.detour.active,
                                    reason=self.detour.reason),
                        nav_mode=self.nav_mode,
                        hybrid_mode=self.hybrid_mode)

    def start(self, mode='profile', expected_track_id=None, expected_profile_id=None, expected_epoch=None):
        with self.lock:
            if expected_epoch is not None and expected_epoch != self.command_epoch:
                raise ValueError('跟随请求已被停车或新指令取消')
            epoch = self.command_epoch
            if self.enabled:
                return self.snapshot()
            if self.detour.active:
                raise ValueError('上一次绕行正在停车，请稍后再试')
            if mode not in ('profile', 'track'):
                raise ValueError('跟随模式无效')
            self.mode = mode
            if self.node.nx_handle is not None or self.node.patrol_mission.active() or self.node.relocalization.running:
                raise ValueError('请先结束导航、巡航或重定位')
            if time.monotonic()-self.people_at > .4:
                raise ValueError('人体识别数据未更新')
            # poll_people may have processed this frame in profile mode before
            # a newly selected anonymous target switched us to track mode.
            # Apply the same two-frame range gate before the first wheel command.
            self.people = self.range_gate.protect(self.people, allow_anonymous=mode == 'track')
            people = self.people
            target = (people or {}).get('target_session') or {}
            if expected_track_id is not None and target.get('track_id') != expected_track_id:
                raise ValueError('所选人体已经变化，请重新选择')
            if expected_profile_id is not None and (target.get('profile_id') != expected_profile_id or
                    target.get('confirmation_source') != 'face_match'):
                raise ValueError('已登记人员尚未通过当前人脸核对')
            age = (people or {}).get('camera_age')
            age = age + time.monotonic()-self.people_at if isinstance(age, (int,float)) else None
            clearance, fresh = self.scan_state()
            rear_clearance, rear_fresh = self.rear_scan_state()
            vx, wz, reason = decide(people, age, clearance, fresh,
                                    allow_anonymous=mode == 'track',
                                    rear_clearance=rear_clearance, rear_scans_fresh=rear_fresh,
                                    predicted_center=self.predicted_center)
            moving_reasons = ('低速跟随', '已保持跟随距离',
                              '目标偏侧，原地转向重新测距', '目标过近，低速退让')
            waiting_reasons = ('前方障碍物过近', '前方空间不足，停车等待',
                               '后方空间不足，不能退让')
            if mode == 'profile':
                # The face-verified person may be locked while furniture
                # temporarily prevents stereo depth. Arm at zero velocity;
                # tick still requires a fresh measured range before motion.
                waiting_reasons += ('双目距离无效',)
            if reason not in moving_reasons + waiting_reasons:
                raise ValueError('跟随条件未满足：'+reason)
            points=[p for topic in ('/scan','/scan_low_filtered')
                    for p in self.scan_points.get(topic,())]
            if not self.nav_mode and follow_motion_blocked(points,vx,wz):
                raise ValueError('跟随条件未满足：近距离障碍挡住当前方向')
            if not self.gate.service_is_ready():
                raise ValueError('底盘跟随开关未就绪')
            future = self.gate.call_async(SetBool.Request(data=not self.nav_mode))
        deadline = time.monotonic()+3
        while not future.done() and time.monotonic()<deadline:
            time.sleep(.02)
        if not future.done() or not future.result().success:
            raise ValueError('底盘拒绝跟随：'+(future.result().message if future.done() else '响应超时'))
        with self.lock:
            if epoch != self.command_epoch:
                self.gate.call_async(SetBool.Request(data=False))
                self.pub.publish(Twist())
                raise ValueError('跟随请求已被停车或新指令取消')
            self.profile_id = people['target_session']['profile_id']
            self.track_id = people['target_session']['track_id']
            self.recovery_candidate_id = None
            self.recovery_candidate_since = None
            self.map_estimator.clear('跟随已停止')
            self.map_last_frame = None
            self.blocked_since = None
            self.enabled = True
            self.reason = ('已启动，停车等待：'+reason if reason in waiting_reasons
                           else '已启动，正在核对连续目标')
        return self.snapshot()

    def stop(self, reason='已手动停止'):
        with self.lock:
            self.command_epoch += 1
            was_enabled = self.enabled
            self.enabled = False
            if self.detour.active:
                self.detour.cancel()
            self.reason = reason
            self.command = (0., 0.)
            self.profile_id = None
            self.track_id = None
            self.recovery_candidate_id = None
            self.recovery_candidate_since = None
            self.map_estimator.clear('跟随已停止')
            self.map_last_frame = None
            self.blocked_since = None
            self.pub.publish(Twist())
            if was_enabled and self.gate.service_is_ready():
                self.gate.call_async(SetBool.Request(data=False))
        return self.snapshot()

    def scan_state(self):
        now = time.monotonic()
        values = [self.scans.get(key) for key in ('/scan', '/scan_low_filtered')]
        fresh = all(row is not None and now-row[0] < .5 and row[1] is not None for row in values)
        return min(row[1] for row in values) if fresh else None, fresh

    def rear_scan_state(self):
        now = time.monotonic()
        values = [self.rear_scans.get(key) for key in ('/scan', '/scan_low_filtered')]
        fresh = all(row is not None and now-row[0] < .5 and row[1] is not None for row in values)
        return min(row[1] for row in values) if fresh else None, fresh

    def tick(self):
        with self.lock:
            if not self.enabled:
                return
            now = time.monotonic()
            if now-self.people_at > .7 or now-self.same_frame_since > 1.25:
                self.stop('人体识别连接或画面中断')
                return
            if self.detour.active:
                self.command = (0., 0.)
                self.reason = self.detour.reason
                # Do not leave the last visual command running while the
                # short map detour is being planned and the gates switch.
                self.pub.publish(Twist())
                return
            if now-self.same_frame_since > .75:
                self.command = (0., 0.)
                self.reason = '相机短暂延迟，停车等待新画面'
                self.pub.publish(Twist())
                return
            people = self.people or {}
            target = people.get('target_session') or {}
            if self.mode == 'profile' and target.get('active') and target.get('profile_id') != self.profile_id:
                self.stop('原目标已丢失或身份变化，请重新选择')
                return
            if not target.get('active'):
                if self.mode == 'profile' and (people.get('face_reacquire') or {}).get('active') is True:
                    # Retain the user's follow request, but never send motion
                    # while the old body identity is missing.
                    self.command = (0., 0.)
                    self.reason = '目标暂时丢失，停车等待人脸重新核对'
                    self.recovery_candidate_id = None
                    self.recovery_candidate_since = None
                    self.pub.publish(Twist())
                    return
                self.stop('原目标已丢失，请重新选择')
                return
            if target.get('track_id') != self.track_id:
                if self.mode == 'track':
                    self.stop('当前人体编号变化，已停车；请重新选择')
                    return
                proof = people.get('face_reacquire_proof') or {}
                proof_age = proof.get('age_s')
                if (proof.get('profile_id') != self.profile_id or
                        proof.get('track_id') != target.get('track_id') or
                        not isinstance(proof_age, (int, float)) or
                        not math.isfinite(proof_age) or not 0 <= proof_age <= 1.5 or
                        target.get('face_verified') is not True):
                    self.stop('目标编号变化且未重新核对人脸')
                    return
                if self.recovery_candidate_id != target['track_id']:
                    self.recovery_candidate_id = target['track_id']
                    self.recovery_candidate_since = now
                if now - self.recovery_candidate_since < .4:
                    self.command = (0., 0.)
                    self.reason = '已找回身份，停车核对连续人体与距离'
                    self.pub.publish(Twist())
                    return
                self.track_id = target['track_id']
                self.recovery_candidate_id = None
                self.recovery_candidate_since = None
            age = people.get('camera_age')
            age = age + now-self.people_at if isinstance(age, (int,float)) else None
            clearance, fresh = self.scan_state()
            rear_clearance, rear_fresh = self.rear_scan_state()
            vx, wz, reason = decide(people, age, clearance, fresh,
                                    allow_anonymous=self.mode == 'track',
                                    rear_clearance=rear_clearance, rear_scans_fresh=rear_fresh,
                                    predicted_center=self.predicted_center)
            if reason == '双目距离无效':
                hint = self.map_estimator.hint(people, now)
                if hint and hint['remaining_robot_travel_m'] > .02:
                    target_id = target.get('track_id')
                    estimated = dict(people)
                    estimated['tracks'] = [dict(row, depth_valid=True,
                                                distance_m=hint['distance_m'])
                                           if row.get('track_id') == target_id else row
                                           for row in people.get('tracks') or []]
                    fallback_v, fallback_w, fallback_reason = decide(
                        estimated, age, clearance, fresh,
                        allow_anonymous=self.mode == 'track',
                        rear_clearance=rear_clearance, rear_scans_fresh=rear_fresh,
                        predicted_center=self.predicted_center)
                    if fallback_reason == '低速跟随' and fallback_v > 0.:
                        # Advance only toward the next map observation pose.
                        # The live body bearing and lidar gates above must
                        # agree; the waypoint cannot extend stale range.
                        vx = min(fallback_v, .16,
                                 hint['remaining_robot_travel_m']*.8,
                                 max(0., (hint['waypoint_forward_m']-.05)*.7))
                        if abs(hint['waypoint_heading_error_rad']) > .28:
                            vx = 0.
                        wz = max(-.25, min(.25,
                                 .5*fallback_w + .7*hint['waypoint_heading_error_rad']))
                        reason = '地图短时观察点；等待双目重新测距'
            if self.nav_mode:
                # Nav2 alone owns wheel commands in this mode. A measured,
                # face/track-associated map point is required for each short
                # observation goal; no direct follow Twist is published.
                started = self.detour.consider_target(people, now)
                if started:
                    self.reason = self.detour.reason
                elif (self.map_estimator.anchor is None or
                      now-self.map_estimator.anchor['received'] > 1.2):
                    self.reason = '等待新的双目地图观测；保持停车'
                else:
                    self.reason = self.detour.reason
                self.command = (0., 0.)
                self.pub.publish(Twist())
                return
            edge_obstacle = (reason == '前方障碍物过近' or
                             (reason == '双目距离无效' and fresh and
                              isinstance(clearance, (int, float)) and
                              clearance < .75))
            if edge_obstacle and self.detour_enabled:
                if self.blocked_since is None:
                    self.blocked_since = now
                if now-self.blocked_since >= 1.2:
                    points = [p for topic in ('/scan', '/scan_low_filtered')
                              for p in self.scan_points.get(topic, ())]
                    if self.detour.consider(people, now, points):
                        reason = self.detour.reason
            else:
                self.blocked_since = None
            if vx or wz:
                points=[p for topic in ('/scan','/scan_low_filtered')
                        for p in self.scan_points.get(topic,())]
                if follow_motion_blocked(points,vx,wz):
                    vx,wz,reason=0.,0.,'近距离障碍，停车等待'
            self.reason = reason
            self.command = (vx, wz)
            twist = Twist()
            twist.linear.x = vx
            twist.angular.z = wz
            self.pub.publish(twist)
