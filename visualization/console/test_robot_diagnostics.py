import json
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from robot_diagnostics import RobotDiagnostics

with tempfile.TemporaryDirectory(prefix='robot-diagnostics-test-') as tmp:
    node=SimpleNamespace(workspace=Path(tmp), lock=threading.Lock(), pose={'x':0,'y':0},
        map_info={}, path=[], current_floor_id='floor_4',
        create_subscription=lambda *args:None, create_timer=lambda *args:None,
        create_client=lambda *args:SimpleNamespace(service_is_ready=lambda:False),
        get_clock=lambda:SimpleNamespace(now=lambda:SimpleNamespace(nanoseconds=int(time.time()*1e9))))
    d=RobotDiagnostics(node)
    d.lifecycle['bt_navigator'] = (time.monotonic(), True, 'active')
    assert next(x for x in d.snapshot()['checks'] if x['label']=='bt_navigator')['ok']
    d.lifecycle['bt_navigator'] = (time.monotonic()-10, True, 'active')
    assert not next(x for x in d.snapshot()['checks'] if x['label']=='bt_navigator')['ok']
    def healthy(label):
        return next(x for x in d.snapshot()['checks'] if x['label']==label)['ok']
    assert not healthy('IMU转速')
    stamp=time.time()
    imu=SimpleNamespace(header=SimpleNamespace(stamp=SimpleNamespace(sec=int(stamp),nanosec=int((stamp%1)*1e9)),frame_id='base_link'),
        angular_velocity=SimpleNamespace(x=0.,y=0.,z=0.),angular_velocity_covariance=[.02]*9)
    d.sensor('IMU转速',imu); assert healthy('IMU转速')
    d.samples['IMU转速']['received']-=1; assert not healthy('IMU转速')
    imu.header.stamp.sec-=10
    d.sensor('IMU转速',imu); assert not healthy('IMU转速')  # Fresh receipt, stale source.
    imu.header.stamp.sec+=20
    d.sensor('IMU转速',imu); assert not healthy('IMU转速')  # Future source.
    imu.angular_velocity.z=float('nan')
    d.sensor('IMU转速',imu); assert not healthy('IMU转速')
    d.status('视觉识别',SimpleNamespace(data='running detections=0'))
    assert healthy('视觉识别')
    d.samples['视觉识别']['received']-=20; assert not healthy('视觉识别')
    assert d.snapshot()['checks'][0]['ok'] is False
    d.samples['高位雷达']={'received':time.monotonic(),'valid':10}
    assert d.snapshot()['checks'][0]['ok'] is True
    d.samples['高位雷达']['received']-=10
    assert d.snapshot()['checks'][0]['ok'] is False
    d.status('导航',SimpleNamespace(data='{"state":"accepted","destination_id":"wp_009"}'))
    d.logs.append(dict(time=time.time(), node='planner_server', message='Starting point in lethal space'))
    d.status('导航',SimpleNamespace(data='{"state":"failed","destination_id":"wp_009","failure_code":"NAVIGATION_FAILED"}'))
    d.pending.result(timeout=5)
    files=list((Path(tmp)/'log/diagnostics').glob('*.json'))
    assert len(files)==1
    evidence=json.loads(files[0].read_text())
    assert evidence['failure']['destination_id']=='wp_009'
    assert '起点被标为障碍' in evidence['summary']
    assert evidence['samples']['高位雷达']['age_sec']>=10
    d.writer.shutdown()
print('PASS: missing/fresh/stale data and failure snapshot persistence; no motion commands')
