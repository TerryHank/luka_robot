import sys
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'control/luka_motion_gateway'))
from luka_motion_gateway.arbiter import MotionArbiter


def setup():
    now=[10.];arbiter=MotionArbiter(clock=lambda:now[0])
    return arbiter,now


def request(arbiter,source='nav',owner='test',mode='acquire',**patch):
    return dict(source=source,owner=owner,mode=mode,boot=arbiter.lease.boot,
                generation=arbiter.lease.generation,**patch)


def test_only_explicitly_leased_source_can_output_velocity():
    a,_=setup();v=[.1,0.,0.,0.,0.,0.]
    assert not a.lease.permits(None)
    assert not a.receive(None,v)
    assert not a.receive('nav',v)
    a.lease.request(request(a));assert a.receive('nav',v);assert a.output()==v
    assert not a.receive('follow',[.2,0.,0.,0.,0.,0.]);assert a.output()==v
    with pytest.raises(ValueError):a.lease.request(request(a,'follow','other'))


def test_command_and_lease_watchdogs_zero_and_invalidate_generation():
    a,now=setup();a.lease.request(request(a));a.receive('nav',[.1,0.,0.,0.,0.,0.])
    generation=a.lease.generation;now[0]+=.26;assert a.output()==[0.]*6
    now[0]+=.4;assert a.output()==[0.]*6;assert a.lease.generation>generation


def test_manual_takeover_and_stop_require_new_explicit_permission():
    a,_=setup();old=request(a);a.lease.request(old);a.receive('nav',[.1,0.,0.,0.,0.,0.])
    a.lease.manual_input('joy',True);assert a.output()==[0.]*6
    with pytest.raises(ValueError):a.lease.request(old)
    with pytest.raises(ValueError):a.lease.request(request(a))
    a.lease.manual_input('joy',False);assert a.output()==[0.]*6
    a.lease.request(request(a));assert a.output()==[0.]*6
    a.receive('nav',[.1,0.,0.,0.,0.,0.]);a.stop();assert a.output()==[0.]*6


def test_explicit_source_switch_cannot_reuse_old_velocity():
    a,_=setup();a.lease.request(request(a));a.receive('nav',[.1,0.,0.,0.,0.,0.])
    a.lease.request(request(a,'relocalize'));assert a.output()==[0.]*6
    assert not a.receive('nav',[.1,0.,0.,0.,0.,0.])
    a.receive('relocalize',[0.,0.,0.,0.,0.,.2]);assert a.output()[-1]==.2


def test_gateway_restart_rejects_previous_boot_and_invalid_velocity():
    a,_=setup();b,_=setup()
    with pytest.raises(ValueError):b.lease.request(request(a))
    b.lease.request(request(b));assert not b.receive('nav',[float('nan')]*6)
    assert b.output()==[0.]*6
