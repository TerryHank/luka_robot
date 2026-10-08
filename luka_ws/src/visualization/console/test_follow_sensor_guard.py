"""Sensor fault injection: no ROS node, hardware, or actual motion output."""
import ast, time, math, json
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock
tree=ast.parse(Path(__file__).with_name('person_follow_node.py').read_text())
cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='PersonFollow')
cls.bases=[]
cls.body=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name in
          ('input_fault','start','stop','tick','image','imu')]
fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='safe_command')
ns=dict(time=time,math=math,json=json,Bool=NS,String=NS,Twist=NS,Empty=NS(Request=NS))
exec(compile(ast.Module(body=[fn,cls],type_ignores=[]),'follow','exec'),ns)
def fresh():
    n=ns['PersonFollow'](); now=time.monotonic()
    n.last_imu=now; n.frame=(now,b'jpeg'); n.last_image_stamp=None
    n.scans={'/scan':(now,2.),'/scan_low_filtered':(now,2.)}
    n.mode='disabled'; n.manual=False; n.epoch=0
    n.active=Mock(); n.cmd=Mock(); n.status=Mock(); n.pause=Mock(); n.resume=Mock()
    n.last_report=now; n.reason='disabled'; n.target=None
    n.get_clock=lambda:NS(now=lambda:NS(nanoseconds=100_000_000_000))
    return n
n=fresh(); assert n.input_fault(time.monotonic()) is None
for sensor in ('imu','camera','lidar'):
    n=fresh()
    if sensor=='imu': n.last_imu=None
    elif sensor=='camera': n.frame=(time.monotonic()-2,b'jpeg')
    else: n.scans['/scan']=(time.monotonic()-2,2.)
    n.start(NS(),NS()); assert n.mode=='disabled' and not n.pause.call_async.called
    n.mode='tracking'; n.tick()
    assert n.mode=='disabled' and n.cmd.publish.call_count==1 and n.active.publish.call_args.args[0].data is False
    # Healthy data returning must NOT implicitly restart the follower.
    now=time.monotonic(); n.last_imu=now; n.frame=(now,b'jpeg'); n.scans={k:(now,2.) for k in n.scans}
    n.tick(); assert n.mode=='disabled' and n.cmd.publish.call_count==1
n=fresh(); n.start(NS(),NS()); assert n.mode=='pausing' and n.pause.call_async.called
n=fresh(); msg=NS(header=NS(stamp=NS(sec=100,nanosec=0)),data=b'jpeg')
n.image(msg); frame=n.frame; n.image(msg); assert n.frame is frame
n=fresh(); n.last_imu=None
imu=NS(header=NS(stamp=NS(sec=100,nanosec=0)),angular_velocity_covariance=[.02]*9,
       angular_velocity=NS(x=0.,y=0.,z=float('nan')))
n.imu(imu); assert n.last_imu is None
imu.angular_velocity.z=0.; n.imu(imu); assert n.last_imu is not None
print('PASS: startup gates, IMU/camera/lidar loss stops, no automatic restart, repeated camera frame, invalid IMU')
