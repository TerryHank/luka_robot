"""Dashboard command adapter for the single official person-following owner."""
import re
import threading
import time

from rcl_interfaces.srv import GetParameters
from rclpy.qos import QoSProfile, DurabilityPolicy
from std_msgs.msg import String
from std_srvs.srv import SetBool


class FollowController:
    supports_selected_identity = False

    def __init__(self, node):
        self.node = node
        self.lock = threading.RLock()
        self.command_epoch = 0
        self._enabled = False
        self._seen = 0.0
        self.output_mode = None
        self.reason = '等待官方跟随模块；人脸识别不等于指定身份跟随'
        self.status = 'DISABLED'
        self.track_id = None
        self.diagnostic = ''
        self._mode_future = None
        self._enable_future = None
        self._enable_epoch = None
        self.gate = node.create_client(SetBool, '/person_follow/enable_follow')
        self.parameters = node.create_client(
            GetParameters, '/person_follow/tros_person_following_node/get_parameters')
        qos = QoSProfile(depth=10, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        node.create_subscription(String, '/person_follow/tros_tracking_status', self.on_status, qos)
        node.create_subscription(String, '/person_follow/integration_diagnostics', self.on_diagnostic, qos)
        node.create_timer(0.5, self.read_mode)

    @property
    def enabled(self):
        with self.lock:
            pending = self._enable_epoch == self.command_epoch and self._enable_future is not None and not self._enable_future.done()
            return self.gate.service_is_ready() and (pending or (self._enabled and time.monotonic() - self._seen < 2.0))

    def read_mode(self):
        if not self.parameters.service_is_ready() or (self._mode_future and not self._mode_future.done()):
            return
        self._mode_future = self.parameters.call_async(GetParameters.Request(names=['output_mode']))
        self._mode_future.add_done_callback(self.mode_response)

    def mode_response(self, future):
        result = future.result()
        if result and result.values:
            with self.lock:
                self.output_mode = result.values[0].string_value

    def on_status(self, msg):
        match = re.search(r'(?:FollowStatus |follow status: )([A-Z_]+)', msg.data)
        if not match:
            return
        identity = re.search(r':id=(\d+)', msg.data)
        with self.lock:
            self.status = match.group(1)
            self._enabled = self.status != 'DISABLED'
            self.track_id = int(identity.group(1)) if identity else None
            self._seen = time.monotonic()

    def on_diagnostic(self, msg):
        mode, _, reason = msg.data.partition(': ')
        with self.lock:
            if mode in ('dry_run', 'nav2_action'):
                self.output_mode = mode
            self.diagnostic = reason
            self.reason = reason or self.reason
            self._seen = time.monotonic()

    def snapshot(self):
        with self.lock:
            available = self.gate.service_is_ready()
            known_mode = self.output_mode in ('dry_run', 'nav2_action')
            return dict(enabled=self.enabled, mode='official', output_mode=self.output_mode,
                        module_available=available, supports_selected_identity=False,
                        reason=self.reason, status=self.status, target_track_id=self.track_id,
                        target_profile_id=None, forward_m_s=None, yaw_rad_s=None,
                        ready=available and known_mode and 'BLOCKED' not in self.diagnostic,
                        ready_reason=self.diagnostic or self.reason,
                        options=dict(profiles=[], selected_track_id=self.track_id, selected_track=None),
                        nav_mode=self.output_mode == 'nav2_action', hybrid_mode=False,
                        detour=dict(enabled=False, active=False, reason='路径执行由现有Nav2负责'),
                        map_assist={}, range_guard_reason='距离、TF和地图门控由官方核心执行')

    def start(self, mode='official', expected_track_id=None, expected_profile_id=None, expected_epoch=None):
        if mode != 'official' or expected_track_id is not None or expected_profile_id is not None:
            raise ValueError('新版使用官方MOT动态选人，不支持把人脸或旧人体编号作为指定跟随身份')
        if not self.gate.service_is_ready():
            raise ValueError('请先启动 s100_person_following_integration；本接口不另起跟随控制器')
        with self.lock:
            if self.output_mode not in ('dry_run', 'nav2_action'):
                raise ValueError('官方运行模式尚未读到，请等待状态更新')
            if expected_epoch is not None and expected_epoch != self.command_epoch:
                raise ValueError('启动请求已经取消')
            if self.node.nx_handle is not None or self.node.patrol_mission.active() or self.node.relocalization.running:
                raise ValueError('请先结束导航、巡航或重定位')
            epoch = self.command_epoch
        future = self.gate.call_async(SetBool.Request(data=True))
        with self.lock:
            self._enable_future, self._enable_epoch = future, epoch
            self.reason = '等待官方模块确认启用'
        future.add_done_callback(lambda response: self.cancel_late_enable(response, epoch))
        deadline = time.monotonic() + 3.0
        while not future.done() and time.monotonic() < deadline:
            time.sleep(0.02)
        if not future.done() or not future.result() or not future.result().success:
            with self.lock:
                if self.command_epoch == epoch:
                    self.command_epoch += 1
            self.gate.call_async(SetBool.Request(data=False))
            raise ValueError('官方跟随未确认启用，已请求关闭')
        with self.lock:
            if epoch != self.command_epoch:
                self.gate.call_async(SetBool.Request(data=False))
                raise ValueError('启动期间收到停止请求，已保持关闭')
            self._enabled = True
            self._seen = time.monotonic()
            self.reason = ('候选目标观察已启用，不发送运动目标' if self.output_mode == 'dry_run'
                           else '官方跟随已启用，运动门控由现有Nav2与底盘负责')
        return self.snapshot()

    def cancel_late_enable(self, future, epoch):
        result = future.result()
        with self.lock:
            stale = epoch != self.command_epoch
        if stale and result and result.success:
            self.gate.call_async(SetBool.Request(data=False))

    def stop(self, reason='已请求停止跟随'):
        with self.lock:
            self.command_epoch += 1
            self.reason = reason
        if self.gate.service_is_ready():
            future = self.gate.call_async(SetBool.Request(data=False))
            future.add_done_callback(self.stop_response)
        return self.snapshot()

    def stop_response(self, future):
        result = future.result()
        if result and result.success:
            with self.lock:
                self._enabled = False
                self._seen = time.monotonic()
                self.reason = '官方跟随已关闭；实际停稳由已有导航安全链确认'
