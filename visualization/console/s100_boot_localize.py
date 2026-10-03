#!/usr/bin/env python3
"""After boot, seed AMCL from a verified saved pose, then validate it by scan.

If the robot was moved while powered off, scan validation fails and AMCL gets
an automatic full-map search. No navigation goal is sent by this script.
"""
import json
import math
import sys
import time
from urllib.request import Request, urlopen

from s100_boot_pose import load_saved_pose, strong_match, write_pose, navigation_verified

BASE='http://127.0.0.1:8503'


def request(path,body=None):
    payload=None if body is None else json.dumps(body).encode()
    req=Request(BASE+path,data=payload,
                headers={'Content-Type':'application/json'} if payload is not None else {},
                method='POST' if payload is not None else 'GET')
    with urlopen(req,timeout=7) as response:
        return json.load(response)


def sensors_ready(result):
    checks={item['name']:item['ready'] for item in result['health']['checks']}
    return all(checks.get(name) for name in ('高位雷达','低位雷达','轮式里程计','导航接口'))


def wait_result(seconds):
    deadline=time.monotonic()+seconds
    last=None
    while time.monotonic()<deadline:
        time.sleep(1)
        last=request('/api/localization/candidate')
        if not last.get('running') and last.get('message')!='未发起定位操作':
            return last
    return last


def consistent_pose(first,second):
    a,b=first.get('pose') or {},second.get('pose') or {}
    if not all(key in a and key in b for key in ('x','y','yaw')):
        return False
    distance=math.hypot(a['x']-b['x'],a['y']-b['y'])
    yaw=abs(math.atan2(math.sin(a['yaw']-b['yaw']),math.cos(a['yaw']-b['yaw'])))
    return distance<=.18 and yaw<=.20


def confirm_static(first,seed):
    request('/api/localization/manual',seed)
    second=wait_result(25)
    if second and strong_match(second) and consistent_pose(first,second):
        write_pose(second['pose'],True)
        return True
    return False


def main(static_only=False):
    # The lidar Ethernet links may appear well after the dashboard. Keep
    # waiting instead of giving up before the physical sensors are available.
    while True:
        try:
            status=request('/api/localization/candidate')
            if navigation_verified(status):
                print('Existing verified localization retained',flush=True)
                return 0
            if sensors_ready(request('/api/functions/status')):
                break
        except Exception:
            pass
        time.sleep(3)

    pose=load_saved_pose()
    if pose:
        try:
            print('Seeding AMCL with last verified pose; checking live scans',flush=True)
            request('/api/localization/manual',pose)
            result=wait_result(25)
            if result and strong_match(result):
                # Repeat the static initialization. Ambiguous corner scans
                # can produce two individually plausible but different poses.
                if confirm_static(result,pose):
                    print('Saved pose passed two independent scan checks',flush=True)
                    return 0
                print('Static pose estimates disagree; trying full-map search',flush=True)
        except Exception as exc:
            print('Saved pose could not be verified: '+str(exc),flush=True)

    if static_only:
        print('Static verification inconclusive; no robot motion requested',flush=True)
        return 2
    print('Starting guarded full-map relocalization',flush=True)
    request('/api/localization/auto',{})
    result=wait_result(90)
    if result and strong_match(result):
        if result.get('rotation_progress_rad',0)>=.3:
            write_pose(result['pose'],True)
            print('Global localization verified after multiple viewing angles',flush=True)
            return 0
        if confirm_static(result,result['pose']):
            print('Global localization verified against live scans',flush=True)
            return 0
    print('Localization remains uncertain; navigation stays unverified: '+str(result),flush=True)
    return 1


if __name__=='__main__':
    sys.exit(main(static_only='--static-only' in sys.argv[1:]))
