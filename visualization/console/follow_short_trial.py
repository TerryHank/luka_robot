#!/usr/bin/env python3
"""Run one bounded on-robot follow trial after a fresh preflight.

The independent timer stops following even if status requests stall. This is
for attended commissioning only, never for automatic startup.
"""
import json
import math
import os
import threading
import time
import urllib.request


BASE = 'http://127.0.0.1:8503/api/'
PEOPLE = 'http://127.0.0.1:8098/api/people/follow-state'
DURATION_S = min(5.0, max(1.0, float(os.getenv('FOLLOW_TRIAL_SECONDS', '3'))))


def request(path, body=None):
    data = None if body is None else json.dumps(body).encode()
    url = PEOPLE if path == 'people' else BASE + path
    req = urllib.request.Request(url, data=data,
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=2) as response:
        return json.load(response)


def preflight():
    follow = request('follow/status')
    teleop = request('teleop/status')
    localization = request('localization/status')
    people = request('people')
    target = people.get('target_session') or {}
    tracks = [row for row in people.get('tracks') or []
              if row.get('track_id') == target.get('track_id') and row.get('visible')]
    person = tracks[0] if len(tracks) == 1 else {}
    distance = person.get('distance_m')
    front = follow.get('front_clearance_m')
    rear = follow.get('rear_clearance_m')
    age = people.get('camera_age')
    scans = follow.get('scan_ages_s') or {}
    checks = {
        'follow_stopped': follow.get('enabled') is False,
        'teleop_released': teleop.get('session_active') is False,
        'base_online': teleop.get('base_online') is True,
        'localized': localization.get('ready') is True,
        'known_person': target.get('active') is True and
                        target.get('face_verified') is True and
                        bool(target.get('profile_id')),
        'one_unambiguous_person': len(tracks) == 1 and
                                  not person.get('association_ambiguous'),
        'fresh_camera': isinstance(age, (int, float)) and 0 <= age < .9,
        'fresh_dual_lidar': all(isinstance(scans.get(key), (int, float)) and
                                scans[key] < .3
                                for key in ('/scan', '/scan_low_filtered')),
        'measured_range': person.get('depth_valid') is True and
                          isinstance(distance, (int, float)) and
                          math.isfinite(distance) and 1.7 <= distance <= 2.7,
        'clear_front': isinstance(front, (int, float)) and front >= 1.2,
        'clear_rear': isinstance(rear, (int, float)) and rear >= .8,
        'continuous_mode': follow.get('nav_mode') is False and
                           follow.get('hybrid_mode') is True,
    }
    return checks, {'distance_m': distance, 'camera_age_s': age,
                    'front_m': front, 'rear_m': rear,
                    'pose': localization.get('pose')}


def main():
    checks, context = preflight()
    print(json.dumps({'preflight': checks, 'context': context},
                     ensure_ascii=False), flush=True)
    if not all(checks.values()):
        raise SystemExit('试跑条件不足；车轮保持停止')
    stop_result = {}

    def stop():
        try:
            stop_result['response'] = request('follow/stop', {})
        except Exception as exc:
            stop_result['error'] = str(exc)

    timer = threading.Timer(DURATION_S, stop)
    timer.daemon = True
    timer.start()
    start_at = time.monotonic()
    try:
        started = request('follow/start', {})
        print(json.dumps({'started': started.get('enabled'),
                          'reason': started.get('reason')},
                         ensure_ascii=False), flush=True)
        if not started.get('enabled'):
            return
        while time.monotonic()-start_at < DURATION_S+.5:
            state = request('follow/status')
            print(json.dumps({'elapsed_s': round(time.monotonic()-start_at, 2),
                              'enabled': state.get('enabled'),
                              'reason': state.get('reason'),
                              'velocity_m_s': state.get('forward_m_s'),
                              'yaw_rad_s': state.get('yaw_rad_s'),
                              'front_m': state.get('front_clearance_m'),
                              'detour': (state.get('detour') or {}).get('reason')},
                             ensure_ascii=False), flush=True)
            if not state.get('enabled'):
                break
            time.sleep(.2)
    finally:
        timer.cancel()
        stop()
        print(json.dumps({'stop': stop_result.get('response', {}).get('reason'),
                          'stop_error': stop_result.get('error')},
                         ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
