"""Experimental translation limits for display only; never sends motor commands.
Deceleration/latency assumptions require real braking validation before enforcement.
"""
import math,time
DIRECTIONS={'forward':((7,15),(29,31)),'left':((32,33),),'right':((13,16),)}
MAX_AGE=.8
REACTION=.8
DECEL=.35
MARGIN=.10
TRIGGER_RANGE=.80

def recommend(data,direction,speed,now=None):
    now=time.time() if now is None else now
    base={'direction':direction,'requested_mps':speed,'enforced':False}
    def stop(reason):return dict(base,state='stop',cap_mps=0.,reason=reason)
    if not isinstance(speed,(int,float)) or not math.isfinite(speed) or speed<0:return stop('速度参数无效')
    if direction not in DIRECTIONS:return dict(base,state='uncovered',cap_mps=None,reason='超声波没有完整覆盖该运动，需要雷达与车身轮廓保护')
    try:
        age=now-data['updated_at']
        if not math.isfinite(age) or not 0<=age<=MAX_AGE:return stop('采集服务数据过期')
        needed=DIRECTIONS[direction];values=[]
        for pins in needed:
            matches=[r for r in data['channels'] if tuple(r['pins'])==pins]
            if len(matches)!=1:return stop('传感器缺失或重复')
            r=matches[0];age=now-r['sample_at'];distance=r['distance_m']
            if not math.isfinite(age) or not 0<=age<=MAX_AGE:return stop('方向传感器数据过期')
            if r.get('status')!='echo' or not isinstance(distance,(int,float)) or not math.isfinite(distance) or not .02<=distance<=5:return stop('方向传感器无有效回波')
            if distance<=TRIGGER_RANGE:values.append(distance-(.08 if direction=='forward' else 0.))
        if not values:return dict(base,state='no_limit',cap_mps=speed,reason='有效原始距离均大于 80 cm，不触发超声波限速')
        clearance=min(values)
        cap=max(0.,math.sqrt((DECEL*REACTION)**2+2*DECEL*max(0.,clearance-MARGIN))-DECEL*REACTION)
        cap=min(speed,cap)
        return dict(base,state='stop' if cap<.03 and speed>0 else 'slow' if cap<speed else 'no_limit',cap_mps=0. if cap<.03 and speed>0 else round(cap,3),clearance_m=round(clearance,3),reason='试算结果；尚未验证制动能力，不代表安全通行',assumptions={'reaction_s':REACTION,'decel_mps2':DECEL,'margin_m':MARGIN})
    except (TypeError,ValueError,KeyError):return stop('传感器数据格式异常')

def preview(data):
    return [recommend(data,'forward',.4),recommend(data,'left',.15),recommend(data,'right',.15),recommend(data,'reverse',.15),recommend(data,'rotate',.3)]

def filter_velocity(data,vx,vy,wz,now=None):
    """Compute a candidate command only. No I/O, no automatic steering.
    Uniform scaling preserves the requested translation/rotation relationship.
    Reverse/rotation require the existing lidar system; not covered by sonar alone.
    """
    if not all(isinstance(v,(int,float)) and math.isfinite(v) for v in (vx,vy,wz)):
        return {'command':[0.,0.,0.],'scale':0.,'decisions':[],'reason':'速度输入无效','coverage_complete':False}
    checks=[]
    if vx>0:checks.append(recommend(data,'forward',vx,now))
    if vy>0:checks.append(recommend(data,'left',vy,now))
    elif vy<0:checks.append(recommend(data,'right',-vy,now))
    scale=min([1.]+[r['cap_mps']/r['requested_mps'] for r in checks])
    return {'command':[vx*scale,vy*scale,wz*scale],'scale':scale,'decisions':checks,'coverage_complete':vx>=0 and wz==0,'reason':'仅生成候选速度；倒车及转弯仍需要激光雷达保护'}
