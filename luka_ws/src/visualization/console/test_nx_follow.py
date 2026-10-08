"""Safety checks for the S100 first-pass follow controller."""
import math
import threading
import time
import unittest
from types import SimpleNamespace

from nx_follow import FollowController, decide, project_target
from person_range_gate import PersonRangeGate
from nx_follow_map import MapFollowEstimate
from test_nx_follow_map import context, reading


def person(depth_valid=True):
    return dict(active=True, loading=False, error=None, camera_age=.2,
                metric_depth_available=True, frame_width=640,
                target_session=dict(active=True, visible=True, face_verified=True,
                                    profile_id='owner', track_id=3),
                enrollment=dict(active=False),
                tracks=[dict(track_id=3, selected=True, visible=True,
                             bbox=[260, 50, 380, 430],
                             depth_valid=depth_valid, distance_m=1.7,
                             observation_strength='strong', association_ambiguous=False)])


class FollowSafetyTest(unittest.TestCase):
    @staticmethod
    def running_controller(people):
        controller = FollowController.__new__(FollowController)
        now = time.monotonic()
        sent = []
        controller.lock = threading.RLock()
        controller.enabled = True
        controller.mode = 'profile'
        controller.command_epoch = 0
        controller.people = people
        controller.people_at = now
        controller.same_frame_since = now
        controller.profile_id = 'owner'
        controller.track_id = 3
        controller.recovery_candidate_id = None
        controller.recovery_candidate_since = None
        controller.command = (0., 0.)
        controller.scan_points = {}
        controller.rear_scans = {}
        controller.predicted_center = None
        controller.map_estimator = MapFollowEstimate()
        controller.map_last_frame = None
        controller.detour = SimpleNamespace(active=False, reason='未绕行')
        controller.detour_enabled = False
        controller.nav_mode = False
        controller.blocked_since = None
        controller.reason = '跟随中'
        controller.pub = SimpleNamespace(publish=sent.append)
        controller.scan_state = lambda: (1.5, True)
        return controller, sent

    def test_valid_target_in_open_corridor_can_follow(self):
        forward, _, reason = decide(person(), .2, 1., True)
        self.assertEqual(reason, '低速跟随')
        self.assertGreater(forward, 0)

    def test_unknown_distance_and_close_obstacle_stop(self):
        self.assertEqual(decide(person(False), .2, 1., True)[:2], (0., 0.))
        self.assertEqual(decide(person(), .2, .65, True)[:2], (0., 0.))

    def test_near_person_reverses_only_with_clear_rear_scan(self):
        observed = person()
        observed['tracks'][0]['distance_m'] = .95
        reverse, yaw, reason = decide(observed, .2, .55, True,
                                      rear_clearance=1.5, rear_scans_fresh=True)
        self.assertLess(reverse, 0.)
        self.assertGreaterEqual(reverse, -.12)
        self.assertEqual(yaw, 0.)
        self.assertEqual(reason, '目标过近，低速退让')
        self.assertEqual(decide(observed, .2, .55, True,
                                rear_clearance=.65, rear_scans_fresh=True)[:2], (0., 0.))
        self.assertEqual(decide(observed, .2, .55, True,
                                rear_clearance=1.5, rear_scans_fresh=False)[:2], (0., 0.))
        observed['tracks'][0]['depth_valid'] = False
        self.assertEqual(decide(observed, .2, .55, True,
                                rear_clearance=1.5, rear_scans_fresh=True)[:2], (0., 0.))

    def test_short_prediction_leads_only_steering(self):
        first, _ = project_target(None, 3, 100., .4)
        second, lead = project_target(first, 3, 100.4, .5)
        self.assertGreater(lead, .5)
        self.assertLess(lead, .6)
        reset, lead = project_target(second, 4, 100.8, .6)
        self.assertEqual(lead, .6)
        self.assertEqual(reset[3], 0.)

    def test_edge_target_turns_only_with_fresh_clear_lidar(self):
        observed = person(False)
        observed['tracks'][0]['bbox'] = [34, 77, 184, 416]
        vx, yaw, reason = decide(observed, .2, 1.3, True)
        self.assertEqual(vx, 0.)
        self.assertGreater(yaw, 0.)
        self.assertLessEqual(yaw, .45)
        self.assertGreaterEqual(yaw, .30)
        self.assertEqual(reason, '目标偏侧，原地转向重新测距')
        self.assertEqual(decide(observed, .2, 1.3, False)[:2], (0., 0.))
        self.assertEqual(decide(observed, .2, .4, True)[:2], (0., 0.))
        observed['tracks'][0]['association_ambiguous'] = True
        self.assertEqual(decide(observed, .2, 1.3, True)[:2], (0., 0.))

    def test_full_fov_person_left_of_stereo_overlap_turns_to_remeasure(self):
        observed = person(False)
        observed['tracks'][0]['bbox'] = [92, 83, 222, 340]
        vx, yaw, reason = decide(observed, .5, 1.3, True)
        self.assertEqual((vx, reason), (0., '目标偏侧，原地转向重新测距'))
        self.assertGreaterEqual(yaw, .30)

    def test_clicked_anonymous_body_requires_continuity_depth_and_lidar(self):
        observed = person()
        observed['target_session'] = dict(active=True, visible=True,
                                          face_verified=False, profile_id=None,
                                          track_id=3)
        observed['tracks'][0].update(first_seen=1., last_strong_seen=1.4)
        self.assertEqual(decide(observed, .2, 2., True)[:2], (0., 0.))
        self.assertGreater(decide(observed, .2, 2., True, allow_anonymous=True)[0], 0.)
        observed['tracks'][0]['association_ambiguous'] = True
        self.assertEqual(decide(observed, .2, 2., True, allow_anonymous=True)[:2], (0., 0.))
        observed['tracks'][0]['association_ambiguous'] = False
        self.assertEqual(decide(observed, .2, .65, True, allow_anonymous=True)[:2], (0., 0.))
        observed['tracks'][0]['depth_valid'] = False
        self.assertEqual(decide(observed, .2, 2., True, allow_anonymous=True)[:2], (0., 0.))

    def test_clicked_body_cannot_bypass_first_range_gate(self):
        controller = FollowController.__new__(FollowController)
        controller.nav_mode = False
        controller.lock = threading.RLock()
        controller.enabled = False
        controller.mode = 'profile'
        controller.command_epoch = 0
        controller.node = SimpleNamespace(
            nx_handle=None,
            patrol_mission=SimpleNamespace(active=lambda: False),
            relocalization=SimpleNamespace(running=False))
        controller.people_at = time.monotonic()
        controller.people = person()
        controller.people['frame_at'] = 100.
        controller.people['target_session'] = dict(
            active=True, visible=True, face_verified=False,
            profile_id=None, track_id=3)
        controller.people['tracks'][0].update(first_seen=1., last_strong_seen=1.4)
        controller.range_gate = PersonRangeGate()
        controller.scan_state = lambda: (2., True)
        controller.rear_scan_state = lambda: (2., True)
        controller.scan_points = {}
        controller.predicted_center = None
        controller.map_estimator = MapFollowEstimate()
        controller.map_last_frame = None
        controller.detour = SimpleNamespace(active=False, reason='未绕行')
        controller.detour_enabled = False
        controller.blocked_since = None
        with self.assertRaisesRegex(ValueError, '双目距离无效'):
            controller.start(mode='track', expected_track_id=3)

    def test_near_obstacle_arms_follow_and_resumes_when_corridor_clears(self):
        controller = FollowController.__new__(FollowController)
        controller.nav_mode = False
        now = time.monotonic()
        sent = []
        controller.lock = threading.RLock()
        controller.enabled = False
        controller.mode = 'profile'
        controller.command_epoch = 0
        controller.node = SimpleNamespace(
            nx_handle=None,
            patrol_mission=SimpleNamespace(active=lambda: False),
            relocalization=SimpleNamespace(running=False))
        controller.people_at = controller.same_frame_since = now
        controller.people = person()
        controller.range_gate = SimpleNamespace(
            protect=lambda state, allow_anonymous=False: state,
            reason='range_consistent')
        controller.scan_state = lambda: (.67, True)
        controller.rear_scan_state = lambda: (1.5, True)
        controller.scan_points = {}
        controller.predicted_center = None
        controller.map_estimator = MapFollowEstimate()
        controller.map_last_frame = None
        controller.detour = SimpleNamespace(active=False, reason='未绕行')
        controller.detour_enabled = False
        controller.blocked_since = None
        controller.command = (0., 0.)
        controller.pub = SimpleNamespace(publish=sent.append)
        future = SimpleNamespace(done=lambda: True,
                                 result=lambda: SimpleNamespace(success=True))
        controller.gate = SimpleNamespace(service_is_ready=lambda: True,
                                          call_async=lambda request: future)
        controller.snapshot = lambda: dict(enabled=controller.enabled,
                                            reason=controller.reason)
        result = controller.start(mode='profile', expected_track_id=3)
        self.assertTrue(result['enabled'])
        controller.tick()
        self.assertEqual((sent[-1].linear.x, sent[-1].angular.z), (0., 0.))
        controller.scan_state = lambda: (1.5, True)
        controller.tick()
        self.assertGreater(sent[-1].linear.x, 0.)

    def test_verified_profile_waits_without_depth_then_moves_after_measurement(self):
        controller = FollowController.__new__(FollowController)
        controller.nav_mode = False
        now = time.monotonic()
        sent = []
        controller.lock = threading.RLock()
        controller.enabled = False
        controller.mode = 'profile'
        controller.command_epoch = 0
        controller.node = SimpleNamespace(
            nx_handle=None,
            patrol_mission=SimpleNamespace(active=lambda: False),
            relocalization=SimpleNamespace(running=False))
        controller.people_at = controller.same_frame_since = now
        controller.people = person()
        controller.people['tracks'][0].update(depth_valid=False, distance_m=None)
        controller.range_gate = SimpleNamespace(
            protect=lambda state, allow_anonymous=False: state,
            reason='stereo_range_missing')
        controller.scan_state = lambda: (2., True)
        controller.rear_scan_state = lambda: (2., True)
        controller.scan_points = {}
        controller.predicted_center = None
        controller.map_estimator = MapFollowEstimate()
        controller.map_last_frame = None
        controller.detour = SimpleNamespace(active=False, reason='未绕行')
        controller.detour_enabled = False
        controller.blocked_since = None
        controller.command = (0., 0.)
        controller.pub = SimpleNamespace(publish=sent.append)
        future = SimpleNamespace(done=lambda: True,
                                 result=lambda: SimpleNamespace(success=True))
        controller.gate = SimpleNamespace(service_is_ready=lambda: True,
                                          call_async=lambda request: future)
        controller.snapshot = lambda: dict(enabled=controller.enabled,
                                            reason=controller.reason)
        self.assertTrue(controller.start(mode='profile', expected_track_id=3)['enabled'])
        controller.tick()
        self.assertEqual((sent[-1].linear.x, sent[-1].angular.z), (0., 0.))
        controller.people['tracks'][0].update(depth_valid=True, distance_m=2.)
        controller.tick()
        self.assertGreater(sent[-1].linear.x, 0.)

    def test_guarded_range_jump_cannot_become_wheel_command(self):
        gate = PersonRangeGate()
        observed = person()
        observed['frame_at'] = 100.
        self.assertEqual(decide(gate.protect(observed), .2, 2., True)[:2], (0., 0.))
        observed['frame_at'] = 100.2
        self.assertGreater(decide(gate.protect(observed), .2, 2., True)[0], 0.)
        observed['frame_at'] = 100.4
        observed['tracks'][0]['distance_m'] = 3.3
        self.assertEqual(decide(gate.protect(observed), .2, 2., True)[:2], (0., 0.))

    def test_speed_rises_only_with_person_distance_and_clear_corridor(self):
        observed = person()
        observed['tracks'][0]['distance_m'] = 2.2
        open_speed, _, _ = decide(observed, .2, 2., True)
        near_obstacle_speed, _, _ = decide(observed, .2, .9, True)
        self.assertGreater(open_speed, .2)
        self.assertLessEqual(open_speed, .40)
        self.assertAlmostEqual(open_speed, .40)
        self.assertAlmostEqual(near_obstacle_speed, .0825)

    def test_nav_mode_never_publishes_direct_follow_velocity(self):
        controller, sent = self.running_controller(person())
        controller.nav_mode = True
        controller.detour.consider_target = lambda observed, now: False
        controller.tick()
        self.assertEqual((sent[-1].linear.x, sent[-1].angular.z), (0., 0.))
        self.assertIn('地图', controller.reason)

    def test_steering_does_not_accelerate_towards_edge_target(self):
        observed = person()
        observed['tracks'][0]['distance_m'] = 2.4
        observed['tracks'][0]['bbox'] = [375, 50, 555, 430]
        forward, yaw, reason = decide(observed, .2, 2.5, True)
        self.assertEqual(reason, '低速跟随')
        self.assertLessEqual(forward, .10)
        self.assertLess(yaw, 0.)

    def test_side_obstacle_outside_body_corridor(self):
        controller = FollowController.__new__(FollowController)
        controller.lock = threading.RLock()
        controller.scans = {}
        controller.rear_scans = {}
        controller.scan_points = {}
        # A real return at x=0.72, y=0.35 lies outside the 0.19 m half-body
        # plus 0.13 m margin. A centre return at x=1.0 remains in the lane.
        side_angle = math.atan2(.35, .72 + .065)
        scan = SimpleNamespace(angle_min=side_angle, angle_increment=-side_angle,
                               ranges=[math.hypot(.72 + .065, .35), 1.065],
                               range_min=.15, range_max=8.)
        controller.on_scan('/scan', scan)
        self.assertAlmostEqual(controller.scans['/scan'][1], 1.0, places=2)

    def test_frontal_obstacle_still_blocks(self):
        controller = FollowController.__new__(FollowController)
        controller.lock = threading.RLock()
        controller.scans = {}
        controller.rear_scans = {}
        controller.scan_points = {}
        scan = SimpleNamespace(angle_min=0., angle_increment=.1,
                               ranges=[.715], range_min=.15, range_max=8.)
        controller.on_scan('/scan', scan)
        self.assertAlmostEqual(controller.scans['/scan'][1], .65, places=2)

    def test_lost_body_waits_at_zero_and_fresh_face_recovery_resumes(self):
        missing = person()
        missing['target_session'] = dict(active=False, profile_id=None)
        missing['tracks'] = []
        missing['face_reacquire'] = dict(active=True)
        controller, sent = self.running_controller(missing)
        controller.tick()
        self.assertTrue(controller.enabled)
        self.assertEqual((sent[-1].linear.x, sent[-1].angular.z), (0., 0.))
        recovered = person()
        recovered['target_session']['track_id'] = 4
        recovered['tracks'][0]['track_id'] = 4
        recovered['face_reacquire_proof'] = dict(track_id=4, profile_id='owner', age_s=.2)
        controller.people = recovered
        controller.tick()
        self.assertEqual(controller.track_id, 3)
        self.assertEqual(sent[-1].linear.x, 0.)
        controller.recovery_candidate_since = time.monotonic() - .5
        controller.tick()
        self.assertEqual(controller.track_id, 4)
        self.assertGreater(sent[-1].linear.x, 0.)

    def test_new_id_without_face_recovery_proof_never_drives(self):
        changed = person()
        changed['target_session']['track_id'] = 4
        changed['tracks'][0]['track_id'] = 4
        controller, sent = self.running_controller(changed)
        stopped = []
        controller.stop = stopped.append
        controller.tick()
        self.assertEqual(stopped, ['目标编号变化且未重新核对人脸'])
        self.assertFalse(sent)

    def test_anonymous_body_id_change_always_stops(self):
        changed = person()
        changed['target_session'] = dict(active=True, visible=True,
                                         face_verified=False, profile_id=None,
                                         track_id=4)
        changed['tracks'][0]['track_id'] = 4
        controller, sent = self.running_controller(changed)
        controller.mode = 'track'
        controller.profile_id = None
        stopped = []
        controller.stop = stopped.append
        controller.tick()
        self.assertEqual(stopped, ['当前人体编号变化，已停车；请重新选择'])
        self.assertFalse(sent)

    def test_short_camera_gap_stops_wheels_without_ending_follow(self):
        controller, sent = self.running_controller(person())
        controller.same_frame_since = time.monotonic() - .95
        controller.tick()
        self.assertTrue(controller.enabled)
        self.assertEqual((sent[-1].linear.x, sent[-1].angular.z), (0., 0.))
        self.assertEqual(controller.reason, '相机短暂延迟，停车等待新画面')

    def test_switching_from_visual_follow_to_map_detour_commands_zero(self):
        controller, sent = self.running_controller(person())
        controller.tick()
        self.assertGreater(sent[-1].linear.x, 0.)
        controller.detour.active = True
        controller.detour.reason = '正在规划绕行路径'
        controller.tick()
        self.assertEqual((sent[-1].linear.x, sent[-1].angular.z), (0., 0.))
        self.assertEqual(controller.reason, '正在规划绕行路径')

    def test_short_map_observation_moves_only_with_visible_same_person(self):
        observed = person(False)
        observed['frame_at'] = 100.4
        observed['tracks'][0]['bbox_bearing_rad'] = 0.
        controller, sent = self.running_controller(observed)
        controller.scan_state = lambda: (2.5, True)
        now = time.monotonic()
        seed = reading(100.)
        controller.map_estimator.observe(seed, context(100.), now=now-.4)
        controller.map_estimator.observe(observed, context(100.4, x=.05), now=now)
        controller.tick()
        self.assertGreater(sent[-1].linear.x, 0.)
        self.assertLessEqual(sent[-1].linear.x, .16)
        self.assertIn('地图短时观察点', controller.reason)

        observed['tracks'][0]['bbox_bearing_rad'] = .6
        observed['frame_at'] = 100.5
        controller.map_estimator.observe(observed, context(100.5, x=.05), now=now+.1)
        controller.tick()
        self.assertEqual(sent[-1].linear.x, 0.)

    def test_long_camera_gap_ends_follow(self):
        controller, sent = self.running_controller(person())
        controller.same_frame_since = time.monotonic() - 1.4
        stopped = []
        controller.stop = stopped.append
        controller.tick()
        self.assertEqual(stopped, ['人体识别连接或画面中断'])
        self.assertFalse(sent)


if __name__ == '__main__':
    unittest.main()
