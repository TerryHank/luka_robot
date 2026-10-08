"""Official strategy through mock Nav2 actions; isolated domains and no motor outputs."""
import signal
import time
import pytest
from nav2_msgs.action import Spin
from test_core_ros import Harness


@pytest.fixture
def harness(tmp_path):
    instances=[]
    def create(**kwargs):
        h=Harness(tmp_path,**kwargs);instances.append(h);return h
    yield create
    for h in instances:h.close()


def idle(h):
    h.people=[];h.enable()


def test_idle_search_and_total_timeout(harness):
    h=harness(mode='nav2_action',overrides={'idle_search_start_timeout_sec':.1,'idle_search_total_timeout_sec':.8})
    idle(h);h.until(lambda:len(h.spins)>0)
    assert 3.0<abs(h.spins[0])<3.2
    h.until(lambda:bool(h.spin_cancels),timeout=2)
    before=len(h.spins);h.wait(.5)
    assert len(h.spins)==before and not h.goals


def test_dry_run_rotates_candidate_only(harness):
    h=harness(overrides={'idle_search_start_timeout_sec':.1})
    idle(h);h.until(lambda:bool(h.spin_candidates))
    assert not h.spins and not h.goals
    endpoints=h.node.get_publisher_names_and_types_by_node('tros_person_following_node','/follow')
    assert all('geometry_msgs/msg/Twist' not in types for _,types in endpoints)
    assert any('SPIN_CANDIDATE' in message for message in h.diagnostics)


@pytest.mark.parametrize('fault',['stale','moving'])
def test_rotation_requires_fresh_measured_stop(harness,fault):
    h=harness(mode='nav2_action',overrides={'idle_search_start_timeout_sec':.1})
    if fault=='stale':h.odom_enabled=False;h.wait(.7)
    else:h.odom_velocity=.2;h.wait(.2)
    idle(h);h.wait(.5)
    assert not h.spins
    h.odom_enabled=True;h.odom_velocity=0.
    h.until(lambda:bool(h.spins))


def test_edge_turn_waits_for_navigation_terminal(harness):
    h=harness(mode='nav2_action');h.track();h.until(lambda:bool(h.goals))
    h.bbox_x,h.bbox_width=500,120
    h.people=[(42,1.1,.3)]
    h.until(lambda:bool(h.spins))
    assert .15<h.spins[-1]<.4
    assert any('TRACKING_EDGE_TURN' in s for s in h.status)
    nav_end=max(event[1] for event in h.nav_events if event[0]=='end')
    assert nav_end<=h.spin_events[0][1]


def test_official_withhold_preserves_existing_goal(harness):
    h=harness(mode='nav2_action');h.track();h.until(lambda:bool(h.goals))
    before=len(h.cancels);h.people=[(42,1.7,0.)];h.wait(.5)
    assert len(h.cancels)==before
    assert not h.handles[-1].is_cancel_requested
    h.people=[(42,1.2,0.)]
    h.until(lambda:len(h.cancels)>before)


def test_moving_target_updates_navigation_without_waiting_for_arrival(harness):
    h=harness(mode='nav2_action');h.track();h.until(lambda:bool(h.goals))
    before=len(h.goals);h.people=[(42,4.,0.)]
    h.until(lambda:len(h.goals)>before)
    assert not h.cancels


def test_acquired_target_waits_for_spin_terminal_before_navigation(harness):
    h=harness(mode='nav2_action',overrides={'idle_search_start_timeout_sec':.1})
    idle(h);h.until(lambda:bool(h.spins))
    h.track();h.until(lambda:bool(h.goals))
    spin_end=max(e[1] for e in h.spin_events if e[0]=='end')
    assert spin_end<=h.nav_events[0][1]


@pytest.mark.parametrize('delay',[0.,1.2])
def test_shutdown_cancels_pending_and_active_spin(harness,delay):
    h=harness(mode='nav2_action',spin_delay=delay,overrides={'idle_search_start_timeout_sec':.1})
    idle(h);h.until(lambda:any('SPIN_SENT' in s for s in h.diagnostics))
    h.process.send_signal(signal.SIGINT)
    assert h.process.wait(5)==0
    assert h.spin_cancels


def lost_scan(h):
    h.track();h.nav_auto_finish=True;h.people=[]
    h.until(lambda:bool(h.spins),timeout=4)
    assert any('LOST_BELIEF_SCAN' in s for s in h.status)


def test_lost_scan_success_advances_next_observation(harness):
    h=harness(mode='nav2_action',overrides={'belief_search_timeout_sec':4.,'predict_lead_sec':0.,'idle_search_start_timeout_sec':10.})
    lost_scan(h)
    before=len(h.goals);h.spin_finish='success'
    h.until(lambda:len(h.goals)>before,timeout=3)
    assert any('round=1' in s for s in h.status)


def test_failed_scan_does_not_report_completion_or_advance(harness):
    h=harness(mode='nav2_action',overrides={'belief_search_timeout_sec':4.,'predict_lead_sec':0.,'idle_search_start_timeout_sec':10.})
    lost_scan(h);before=len(h.goals);h.spin_finish='abort'
    h.until(lambda:any('SPIN_RESULT' in s for s in h.diagnostics))
    h.wait(.4)
    assert len(h.goals)==before
    assert not any('round=1' in s for s in h.status)


def test_relock_interrupts_scan_without_late_progress(harness):
    h=harness(mode='nav2_action',overrides={'belief_search_timeout_sec':4.,'predict_lead_sec':0.})
    lost_scan(h);h.people=[(42,.7,0.)]
    h.until(lambda:bool(h.spin_cancels))
    h.until(lambda:'TRACKING:id=42' in h.status[-1])
    h.wait(.5)
    assert not any('round=1' in s for s in h.status)


@pytest.mark.parametrize('delay',[0.,1.2])
def test_stop_cancels_owned_spin_and_late_accept_only(harness,delay):
    h=harness(mode='nav2_action',spin_delay=delay,overrides={'idle_search_start_timeout_sec':.1})
    assert h.external_spin.wait_for_server(timeout_sec=3.)
    goal=Spin.Goal();goal.target_yaw=99.;goal.time_allowance.sec=30
    future=h.external_spin.send_goal_async(goal)
    end=time.monotonic()+3
    while not future.done() and time.monotonic()<end:time.sleep(.01)
    assert future.done() and future.result().accepted
    external_id=bytes(future.result().goal_id.uuid)
    idle(h);h.until(lambda:any('SPIN_SENT' in s for s in h.diagnostics))
    h.enable(False);h.wait(delay+.5)
    assert h.spin_cancels and external_id not in h.spin_cancels
    count=len(h.spins);h.wait(.5);assert len(h.spins)==count


@pytest.mark.parametrize('fault',['sensor_timeout','tf_timeout','map_invalid'])
def test_spin_fails_closed_on_input_loss(harness,fault):
    h=harness(mode='nav2_action',overrides={'idle_search_start_timeout_sec':.1})
    idle(h);h.until(lambda:bool(h.spins))
    if fault=='sensor_timeout':h.people_enabled=False
    elif fault=='tf_timeout':h.tf_enabled=False
    else:h.bad_map='unknown'
    h.until(lambda:bool(h.spin_cancels),timeout=2.)
    before=len(h.spins);h.wait(.6)
    assert len(h.spins)==before and not h.goals


@pytest.mark.parametrize('available,reject',[(False,False),(True,True)])
def test_spin_missing_or_rejected_is_blocked(harness,available,reject):
    h=harness(mode='nav2_action',spin_server=available,spin_reject=reject,overrides={'idle_search_start_timeout_sec':.1})
    idle(h)
    h.until(lambda:any(('SPIN_REJECTED' if available else 'spin action server unavailable') in s for s in h.diagnostics))
    assert not h.spins and not h.goals
