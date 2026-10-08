"""Directional body-clearance stop. No steering or reverse commands generated."""
import math,time
PINS={'front':[(7,15),(29,31)],'left':[(32,33)],'right':[(13,16)]}
THRESHOLDS={'front':(.20,.28),'left':(.10,.15),'right':(.10,.15)}
class SonarStop:
    def __init__(self):self.latched=set();self.report={}
    def filter(self,data,vx,vy,wz,now=None):
        now=time.time() if now is None else now
        if not all(math.isfinite(v) for v in (vx,vy,wz)):return (0.,0.,0.)
        directions=[]
        if vx>0:directions.append('front')
        if vy>0:directions.append('left')
        if vy<0:directions.append('right')
        if abs(wz)>.001:directions=['front','left','right']
        scale=1.;reasons=[]
        for direction in directions:
            try:
                if not 0<=now-data['updated_at']<=.8:raise ValueError('采集数据过期')
                distances=[]
                for pins in PINS[direction]:
                    matches=[r for r in data['channels'] if tuple(r['pins'])==pins]
                    if len(matches)!=1:raise ValueError('探头缺失')
                    r=matches[0];d=r['distance_m']
                    if r['status']!='echo' or not 0<=now-r['sample_at']<=.8 or not isinstance(d,(int,float)) or not math.isfinite(d) or not .02<=d<=5:raise ValueError('无有效新回波')
                    distances.append(d-(.08 if direction=='front' else 0) if d<=.8 else float('inf'))
                clearance=min(distances)
                stop,release=THRESHOLDS[direction]
                if clearance<=stop+1e-9:self.latched.add(direction)
                elif clearance>=release-1e-9:self.latched.discard(direction)
                if direction in self.latched:scale=0.;reasons.append(f'{direction}: 车身间距≤{stop*100:.0f}cm，需恢复至{release*100:.0f}cm')
                elif clearance<float('inf'):
                    speed=max(abs(vx),abs(vy),abs(wz)*.5)
                    cap=.12 if clearance<=.40 else .20
                    if speed>cap:scale=min(scale,cap/speed);reasons.append(direction+': 近距离减速')
            except (KeyError,TypeError,ValueError):scale=0.;reasons.append(direction+': 超声波状态未知，停止该方向运动')
        self.report={'updated_at':now,'scale':scale,'reasons':reasons,'thresholds':{k:{'stop_clearance_m':v[0],'release_clearance_m':v[1]} for k,v in THRESHOLDS.items()},'scope':'前进、侧移及转弯；倒车依赖激光雷达','enforced':True}
        return vx*scale,vy*scale,wz*scale
