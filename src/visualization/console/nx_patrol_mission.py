"""Patrol-time semantic memory, scoped retrieval and observation-position guidance."""
import json,time,threading,urllib.request,urllib.error,urllib.parse,uuid,math
from pathlib import Path
from nx_object_target import target_from_job

ROUTE=[('wp_008','厨房'),('wp_009','卧室'),('wp_010','浴室')]

def current_scope(node):
    # Import lazily so non-ROS mission tests can exercise motion interlocks.
    from object_pose_context import map_scope
    scope=map_scope(node)
    if not scope.get('map_scope_valid') or not scope.get('map_id'):
        raise ValueError('当前地图范围未确认：'+str(scope.get('map_scope_reason') or '等待地图'))
    return scope

def describe_entities(query,objects):
    if not objects:return '当前地图的物体记忆中暂未找到'+query+'。尚未记录不代表物品不在。'
    descriptions=[]
    for entity in objects[:3]:
        description=entity.get('description') or entity.get('name_zh') or entity.get('label') or query
        stamp=entity.get('last_seen')
        when=time.strftime('%m月%d日%H点%M分',time.localtime(stamp)) if isinstance(stamp,(int,float)) and math.isfinite(stamp) and stamp>0 else '之前'
        place=('观察点'+entity['area_hint']) if entity.get('area_hint') else '已记录的观察位置'
        descriptions.append('在'+when+'于'+place+'看到过'+description)
    text=('记忆中有'+str(len(objects))+'个匹配物品。' if len(objects)>1 else '找到一条物体记忆。')+'；'.join(descriptions)+'。这是上次看到的位置，物品可能已经移动。'
    if len(objects)>1:text+='请在页面选择其中一个，再说带我去。'
    elif objects[0].get('observation_pose') and not objects[0].get('identity_uncertain'):text+='你可以说带我去，到观察位置后重新确认。'
    else:text+='目前缺少可用于带路的可靠观察位置。'
    return text

def vision(path,body=None):
    req=urllib.request.Request('http://127.0.0.1:8091'+path,
        data=None if body is None else json.dumps(body).encode(),
        headers={'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req,timeout=8) as r:return json.load(r)
    except urllib.error.HTTPError as exc:
        raise ValueError(json.loads(exc.read()).get('error','视觉服务拒绝请求')) from exc

class PatrolMission:
    def __init__(self,node,send,stop,speak,root=None):
        self.node=node;self.send=send;self.stop_nav=stop;self.speak=speak
        self.path=Path(root or '/home/sunrise/luka_ws/src/common/state/patrol_mission.json')
        self.lock=threading.RLock();self.cancel=threading.Event();self.thread=None;self.generation=0
        self.state={'mode':'idle','message':'巡航待命','route':[n for _,n in ROUTE], 'hits':[], 'source':'semantic'}
        interrupted=False
        try:
            saved=json.loads(self.path.read_text())
            self.state.update(saved)
            if 'source' not in saved:self.state['source']='video'
            pending_memory=(self.state.get('source')=='semantic' and
                (self.state.get('memory_cleanup_pending') or self.state.get('verification_session')))
            if self.state['mode'] in ('patrolling','nav_testing','searching','stopping','bringing','verifying') or pending_memory:
                self.state.update(mode='interrupted',message='服务重启中断任务，不自动续航；已保存的物体记忆保留')
                interrupted=True
        except (OSError,ValueError):pass
        if interrupted:
            self.thread=threading.Thread(target=self.recover,daemon=True);self.thread.start()
    def recover(self):
        try:
            for _ in range(20):
                if self.node.nx_gate.service_is_ready():break
                time.sleep(.5)
            self.stop_nav()
            if self.state.get('source')=='nav_test':
                pass  # Navigation-only tests never own the camera or memory service.
            elif self.state.get('source')=='semantic':
                session=self.state.get('verification_session') or self.state.get('session')
                if session:self.stop_memory(session)
                self.update(memory_cleanup_pending=False,verification_session=None)
            else:
                rec=vision('/patrol/status')['recording']
                if rec and rec['id']==self.state.get('session'):vision('/patrol/stop',{})
                vision('/patrol/cancel',{})
            self.update(mode='interrupted',message='重启后的巡航已取消，已有记录保留；不会自动续航')
        except Exception as exc:self.update(mode='failed',message='重启恢复未完成，请手动停止导航：'+str(exc))
    def stop_memory(self,session):
        result=vision('/semantic/stop',{'session_id':session})
        if result.get('ok') is not True or result.get('running'):
            raise ValueError('实时记忆采集仍在收尾，尚未确认停止')
        return result
    def update(self,**kw):
        with self.lock:
            self.state.update(kw);self.state['updated_at']=time.time()
            temp=self.path.with_suffix('.tmp');temp.write_text(json.dumps(self.state,ensure_ascii=False));temp.replace(self.path)
    def snapshot(self):
        with self.lock:return dict(self.state)
    def active(self):return self.thread is not None and self.thread.is_alive()
    def memory_objects(self,query,scope):
        result=vision('/semantic/search?'+urllib.parse.urlencode({'query':query,'map_id':scope['map_id']}))
        if not isinstance(result.get('objects'),list):raise ValueError('物体记忆服务返回无效结果')
        rows=[];seen=set()
        for row in result['objects']:
            if not isinstance(row,dict) or not row.get('confirmed') or row.get('map_id')!=scope['map_id']:continue
            if row.get('floor_id')!=scope['floor_id'] or not row.get('id') or row['id'] in seen:continue
            seen.add(row['id']);rows.append(dict(row,source='semantic',query=query))
        return rows
    def target(self,body=None):
        body=body or {};scope=current_scope(self.node)
        query=(body.get('query') or self.state.get('query') or '').strip()
        if not query:raise ValueError('还没有找物记录，请先说帮我找，再加物品名称')
        # A different query or map must be searched and confirmed first, never reuse cached hits.
        if self.state.get('source')!='semantic' or self.state.get('query')!=query or self.state.get('map_id')!=scope['map_id']:
            raise ValueError('当前物品或地图与上次查找不一致，请先重新查找并确认')
        if body.get('map_id') and body['map_id']!=scope['map_id']:raise ValueError('地图已经改变，请重新查找')
        if self.state.get('mode') not in ('found','verified_candidate','not_visible'):raise ValueError('本次没有可带路的查找结果，请先重新查找')
        rows=self.memory_objects(query,scope)
        if current_scope(self.node)['map_id']!=scope['map_id']:raise ValueError('地图已经改变，请重新查找')
        ident=body.get('object_id') or self.state.get('selected_object_id')
        if ident:
            if ident not in {h.get('id') for h in self.state.get('hits',[])}:raise ValueError('所选物品不在本次查找结果中')
            rows=[r for r in rows if r['id']==ident]
        if not rows:raise ValueError('本次没有找到该物品，请先重新查找')
        if len(rows)>1:raise ValueError('找到多个相似物品，请先在页面选择要去的那个')
        entity=rows[0]
        if entity.get('identity_uncertain'):raise ValueError('物品身份仍有歧义，请先确认画面')
        stamp=entity.get('last_seen',0)
        if not isinstance(stamp,(int,float)) or not math.isfinite(stamp) or stamp<=0 or stamp>time.time()+5:
            raise ValueError('物品观察时间无效，请重新观察')
        # Reuse the checked in-map observation-pose converter, never map_xyz_m (object center).
        job={'id':entity['id'],'query':query,'session':'semantic','hits':[{'seconds':0,'image':entity.get('evidence_url'),
            'observation':{'floor_id':scope['floor_id'],'map_pose_status':'tf_at_capture_time','map_from_base':entity.get('observation_pose')}}]}
        target=target_from_job(job,scope['floor_id'],self.node.map_info)
        target.update(source='semantic',object_id=entity['id'],map_id=scope['map_id'],last_seen=stamp)
        return target
    def bring(self,body):
        if self.active() and self.state['mode']=='searching':
            self.stop();self.thread.join(6)
        with self.lock:
            generation=self.generation
            if self.active() or self.node.nx_handle is not None:raise ValueError('请先停止当前巡航、导航或查找')
            if self.node.relocalization.running:raise ValueError('请先完成定位')
            now=time.monotonic()
            if not self.node.pose or now-self.node.last['pose']>1 or now-self.node.last['scan']>1:
                raise ValueError('当前定位或雷达数据过期')
            target=self.target(body)
            semantic=vision('/semantic/status')
            if semantic.get('running'):raise ValueError('请先停止实时物体记忆采集，再开始带路')
            vision('/model/unload',{})
            if generation!=self.generation:raise ValueError('带路请求已因停车取消，请重新发出指令')
            self.cancel.clear();self.update(mode='bringing',message='正在前往'+target['display_name'],target=target)
            self.thread=threading.Thread(target=self.run_bring,args=(target,),daemon=True);self.thread.start()
            return dict(ok=True,message='带你去上次看到'+target['query']+'的观察位置，到达后再确认。')
    def run_bring(self,target):
        try:
            with self.lock:
                if self.cancel.is_set():return
                if target.get('map_id')!=current_scope(self.node)['map_id']:raise ValueError('地图已经改变，已取消带路')
                if self.cancel.is_set():return
                self.send_observation(target)
            deadline=time.monotonic()+240
            while not self.cancel.wait(.2):
                if target.get('map_id')!=current_scope(self.node)['map_id']:raise ValueError('地图已经改变，已停止带路')
                if self.node.nx_nav_outcome is not None:break
                if time.monotonic()>deadline:raise ValueError('前往观察位置超时')
            if self.cancel.is_set():raise ValueError('已取消带路')
            if self.node.nx_nav_outcome!=4:raise ValueError('到不了'+target.get('display_name','观察位置')+'，我已停在当前位置。接下来要我做什么？')
            self.stop_nav();self.update(mode='verifying',message='已到观察位置，正在重新确认'+target['query'])
            if self.cancel.wait(1):raise ValueError('已取消确认')
            r=self.node.relocalization
            if not r.still_since or time.monotonic()-r.still_since<.7 or time.monotonic()-r.odom_at>1:raise ValueError('小车未停稳，暂不确认物体')
            self.verify_observation(target)
        except Exception as exc:
            self.update(mode='cancelled' if self.cancel.is_set() else 'failed',message=str(exc));self.speak(str(exc))
        finally:
            try:self.stop_nav()
            except Exception:pass
            if self.state['mode']=='bringing':self.update(mode='cancelled',message='带路已取消')
    def verify_observation(self,target):
        # Verification uses the same small YOLOE memory pipeline, including query
        # attribute filtering. Never wake NanoOWL for a colour-bearing query.
        session=uuid.uuid4().hex;started=time.time();scope=current_scope(self.node)
        if scope['map_id']!=target['map_id']:raise ValueError('地图已经改变，取消物品确认')
        ready_at=None;outcome=None
        # Persist before the request: a lost HTTP reply may still have started capture.
        self.update(verification_session=session,memory_cleanup_pending=True)
        try:
            result=vision('/semantic/start',{'session_id':session})
            if not result.get('ok') or result.get('session_id')!=session:raise ValueError('到达后的实时确认未启动')
            deadline=time.monotonic()+30
            while not self.cancel.wait(.5):
                ready=self.memory_health(session,scope,starting=ready_at is None)
                if ready:
                    if ready_at is None:ready_at=time.monotonic()
                    rows=self.memory_objects(target['query'],scope)
                    recent=[row for row in rows if isinstance(row.get('last_seen'),(int,float)) and row['last_seen']>=started]
                    if recent:
                        text='已到上次的观察位置，这次看到了'+target['query']+'候选，请看画面确认。'
                        outcome=('verified_candidate',text);break
                    if time.monotonic()-ready_at>=10:
                        text='已到观察位置，但这次没看到'+target['query']+'，可能移走或被遮挡了。'
                        outcome=('not_visible',text);break
                if time.monotonic()>deadline:raise ValueError('到达后的视觉确认超时')
            if outcome is None:raise ValueError('已取消确认')
        finally:
            self.stop_memory(session)
            self.update(verification_session=None,memory_cleanup_pending=False)
        self.update(mode=outcome[0],message=outcome[1]);self.speak(outcome[1])

    def route_snapshot(self):
        with self.lock:return self.route_store.snapshot()
    def save_route(self,body):
        with self.lock:
            if self.active():raise ValueError('请先停止当前任务再修改巡航路线')
            return self.route_store.save(body)
    def start_nav_test(self,body):
        """Run the saved route a finite number of times without camera work."""
        if not isinstance(body,dict):raise ValueError('请求格式无效')
        cycles=body.get('cycles')
        if type(cycles) is not int or not 1<=cycles<=20:
            raise ValueError('巡航圈数须为 1 至 20 的整数')
        with self.lock:
            generation=self.generation
            if self.active():raise ValueError('已有巡航或查找任务，请先停止')
            if self.state.get('memory_cleanup_pending') or self.state.get('verification_session'):
                raise ValueError('上次物体记忆任务尚未确认收尾，请先完成停止恢复')
            n=self.node;now=time.monotonic()
            if n.nx_handle is not None or n.relocalization.running:raise ValueError('请先结束当前导航或定位')
            if not n.pose or now-n.last['pose']>1:raise ValueError('请先完成并核对地图定位')
            if now-n.last['scan']>1:raise ValueError('雷达数据过期')
            scope=current_scope(n)
            route=self.route_store.document()
            if type(body.get('revision')) is not int or body['revision']!=route['revision']:
                raise ValueError('路线已改变，请刷新并核对后启动')
            points=self.route_store.resolve(route)
            if generation!=self.generation:raise ValueError('巡航请求已因停车取消，请重新发出指令')
            self.cancel.clear()
            self.update(mode='nav_testing',source='nav_test',map_id=scope['map_id'],
                message='导航巡航测试准备启动',route=[p['display_name'] for p in points],
                route_revision=route['revision'],cycles_total=cycles,cycles_completed=0,
                cycle=1,leg=None,leg_index=0,hits=[],session=None,
                memory_cleanup_pending=False,verification_session=None)
            self.thread=threading.Thread(target=self.run_nav_test,
                args=(route,points,cycles,scope['map_id']),daemon=True)
            self.thread.start()
            return dict(ok=True,message='已开始纯导航巡航测试：'+str(cycles)+'圈；不录像、不采集物体记忆。')
    def run_nav_test(self,route,points,cycles,map_id):
        try:
            for cycle in range(1,cycles+1):
                for index,point in enumerate(points,1):
                    name=point['display_name']
                    with self.lock:
                        if self.cancel.is_set():break
                        if current_scope(self.node)['map_id']!=map_id:
                            raise ValueError('地图已改变，导航巡航测试停止')
                        if self.route_store.resolve(route)!=points:
                            raise ValueError('航点位置或名称已改变，请重新核对路线')
                        self.update(cycle=cycle,leg=point['id'],leg_index=index,
                            message=f'导航测试第 {cycle}/{cycles} 圈，第 {index}/{len(points)} 站：前往{name}')
                        if self.cancel.is_set():break
                        self.send(point['id'])
                    deadline=time.monotonic()+240;last_check=0
                    while not self.cancel.wait(.2):
                        if self.node.nx_nav_outcome is not None:break
                        now=time.monotonic()
                        if now-last_check>=1:
                            last_check=now
                            if current_scope(self.node)['map_id']!=map_id:
                                raise ValueError('地图已改变，导航巡航测试停止')
                            if (now-self.node.last['pose']>2 or now-self.node.last['scan']>2):
                                raise ValueError('定位或雷达数据过期，导航巡航测试停止')
                        if now>deadline:raise ValueError(name+'导航超时')
                    if self.cancel.is_set():break
                    if self.node.nx_nav_outcome!=4:
                        raise ValueError(name+'未到达，导航巡航测试停止')
                    self.update(message=f'第 {cycle}/{cycles} 圈已到{name}，停留 {route["dwell_s"]} 秒')
                    if self.cancel.wait(route['dwell_s']):break
                if self.cancel.is_set():break
                self.update(cycles_completed=cycle,message=f'已完成 {cycle}/{cycles} 圈')
            self.update(mode='cancelled' if self.cancel.is_set() else 'complete',
                message=('导航巡航测试已停止，完成 '+str(self.state['cycles_completed'])+' 圈'
                         if self.cancel.is_set() else '导航巡航测试完成，共 '+str(cycles)+' 圈'))
        except Exception as exc:
            self.update(mode='cancelled' if self.cancel.is_set() else 'failed',
                message='导航巡航测试已结束：'+str(exc))
        finally:
            try:self.stop_nav()
            except Exception as exc:self.update(message=self.state['message']+'；停车确认失败：'+str(exc))
            if self.state['mode']=='nav_testing':self.update(mode='cancelled',message='导航巡航测试已停止')
    def start(self,body=None):
        with self.lock:
            generation=self.generation
            if self.active():raise ValueError('已有巡航或查找任务，请先停止')
            if self.state.get('memory_cleanup_pending') or self.state.get('verification_session'):
                raise ValueError('上次物体记忆任务尚未确认收尾，请先完成停止恢复')
            n=self.node;now=time.monotonic()
            if n.nx_handle is not None or n.relocalization.running:raise ValueError('请先结束当前导航或定位')
            if not n.pose or now-n.last['pose']>1:raise ValueError('请先完成并核对地图定位')
            if now-n.last['scan']>1:raise ValueError('雷达数据过期')
            scope=current_scope(n)
            route=self.route_store.document()
            if body and 'revision' in body and body['revision']!=route['revision']:raise ValueError('路线已改变，请刷新并核对后启动')
            points=self.route_store.resolve(route)
            status=vision('/patrol/status')
            if status.get('recording') or (status.get('job') or {}).get('status')=='searching':raise ValueError('录像或识别正在使用相机服务')
            if vision('/semantic/status').get('running'):raise ValueError('已有实时物体记忆采集任务，请先停止')
            session=uuid.uuid4().hex
            if generation!=self.generation:raise ValueError('巡航请求已因停车取消，请重新发出指令')
            self.cancel.clear();self.update(mode='patrolling',source='semantic',map_id=scope['map_id'],message='正在开启实时物体记忆',
                hits=[],query=None,selected_object_id=None,target=None,searched=0,total_sessions=0,
                leg=None,leg_index=0,session=session,route=[p['display_name'] for p in points],route_revision=route['revision'])
            self.thread=threading.Thread(target=self.run_patrol,args=(route,points),daemon=True);self.thread.start()
            return dict(ok=True,message='开始巡航并实时记住物品，依次前往'+'、'.join(p['display_name'] for p in points)+'。')
    def stop(self):
        self.generation+=1
        self.cancel.set()
        nav_test=self.state.get('source')=='nav_test' and self.state.get('mode')=='nav_testing'
        # Do not wait for a vision HTTP call holding the mission lock before braking.
        self.stop_nav()
        with self.lock:
            if self.active():self.update(message='正在停止导航巡航测试' if nav_test else '正在停止任务，已写入的物体记忆保留')
        return dict(ok=True,message='已请求停止导航巡航测试。' if nav_test else '已请求停止，已保存的物体记忆保留。')
    def memory_health(self,session,scope,starting=False):
        status=vision('/semantic/status')
        if status.get('session_id')!=session or not status.get('running'):raise ValueError('实时物体记忆采集已中断或被替换')
        if status.get('error'):raise ValueError('实时物体记忆异常：'+str(status['error']))
        if current_scope(self.node)['map_id']!=scope['map_id']:raise ValueError('巡航期间地图改变')
        if status.get('map_id') and status['map_id']!=scope['map_id']:raise ValueError('采集地图与导航地图不一致')
        now=time.time();frame_at=status.get('last_frame_at') or 0;success_at=status.get('last_success_at') or 0
        pause=status.get('paused_reason')
        expected_pause=pause in ('turning_too_fast','moving_too_fast','blurred_frame')
        # A short visual skip does not invalidate navigation's own sensors. Base
        # its grace on the last successful frame, so polling/reason changes never
        # extend it. Localization/odometry loss and unknown errors still stop the
        # mission; never automatically cancel and resume a navigation goal.
        transient_pause=pause in ('waiting_for_camera','camera_stale','vision_busy')
        limit=2 if transient_pause else (15 if expected_pause and not starting else 10)
        camera_age=status.get('camera_age_s',now-frame_at)
        camera_limit=2 if transient_pause else 4
        ready=(status.get('frames',0)>0 and isinstance(camera_age,(int,float)) and 0<=camera_age<=camera_limit and 0<=now-success_at<=limit)
        if not starting and not ready:raise ValueError('实时识别或相机数据已过期，巡航停止')
        if pause and not starting and not (expected_pause or transient_pause):raise ValueError('实时记忆已暂停：'+str(pause))
        return ready and (not pause or ((expected_pause or transient_pause) and not starting))
    def run_patrol(self,route,points):
        session=self.state.get('session') or uuid.uuid4().hex
        started=False
        try:
            scope=current_scope(self.node)
            self.update(session=session,source='semantic',map_id=scope['map_id'])
            if self.cancel.is_set():return
            started=True  # Stop by our ID even if the HTTP reply is lost after acceptance.
            self.update(memory_cleanup_pending=True,verification_session=None)
            result=vision('/semantic/start',{'session_id':session})
            if not result.get('ok') or result.get('session_id')!=session:raise ValueError('实时物体记忆未确认启动')
            deadline=time.monotonic()+20
            while not self.cancel.is_set():
                if self.memory_health(session,scope,starting=True):break
                if time.monotonic()>deadline:raise ValueError('实时识别尚未就绪，未启动行驶')
                self.cancel.wait(.25)
            for index,point in enumerate(points):
                ident,name=point['id'],point['display_name']
                with self.lock:
                    if self.cancel.is_set():break
                    if self.route_store.resolve(route)!=points:raise ValueError('航点位置或名称已改变，请重新核对路线')
                    self.memory_health(session,scope)
                    self.update(leg=ident,leg_index=index+1,message=f'巡航记忆 {index+1}/{len(points)}：前往'+name)
                    if self.cancel.is_set():break
                    self.send(ident)
                deadline=time.monotonic()+240;last_check=0
                while not self.cancel.wait(.2):
                    if time.monotonic()-last_check>1:
                        self.memory_health(session,scope);last_check=time.monotonic()
                    if self.node.nx_nav_outcome is not None:break
                    if time.monotonic()>deadline:raise ValueError(name+'导航超时')
                if self.cancel.is_set():break
                if self.node.nx_nav_outcome!=4:raise ValueError(name+'到不了，我已停在当前位置。接下来要我做什么？')
                self.update(message='已到'+name+'，停留观察并更新物体记忆')
                deadline=time.monotonic()+route['dwell_s']
                while time.monotonic()<deadline and not self.cancel.wait(min(.5,max(0,deadline-time.monotonic()))):
                    self.memory_health(session,scope)
            self.update(mode='cancelled' if self.cancel.is_set() else 'complete',message='巡航已停止，物体记忆已保存' if self.cancel.is_set() else '巡航完成，物体记忆已保存，可以直接说帮我找加物品名称')
        except Exception as exc:self.update(mode='cancelled' if self.cancel.is_set() else 'failed',message='巡航已结束：'+str(exc))
        finally:
            try:self.stop_nav()
            except Exception as exc:self.update(message=self.state['message']+'；停车确认失败：'+str(exc))
            if started:
                try:
                    self.stop_memory(session)
                    self.update(memory_cleanup_pending=False)
                except Exception as exc:self.update(message=self.state['message']+'；记忆采集收尾待确认：'+str(exc))
            if self.state['mode']=='patrolling':self.update(mode='cancelled',message='巡航已停止，物体记忆已保存')
            self.speak(self.state['message'])
    def search(self,query):
        if not isinstance(query,str) or not 1<=len(query.strip())<=40:raise ValueError('请输入简短物体名称')
        query=query.strip()
        if self.active() and self.state['mode']=='patrolling':
            self.stop();self.thread.join(6)
        with self.lock:
            if self.active():raise ValueError('已有任务正在收尾或查找，请稍后再试')
            scope=current_scope(self.node)
            self.stop_nav();self.cancel.clear()
            self.update(mode='searching',source='semantic',map_id=scope['map_id'],query=query,message='正在查询当前地图的物体记忆',hits=[],selected_object_id=None,target=None)
            self.thread=threading.Thread(target=self.run_search,args=(scope,query),daemon=True);self.thread.start()
            return dict(ok=True,message='正在物体记忆中查找'+query+'。')
    def run_search(self,scope,query):
        try:
            hits=self.memory_objects(query,scope)
            with self.lock:
                if self.cancel.is_set():self.update(mode='cancelled',hits=[],selected_object_id=None,message='查找已停止')
                elif current_scope(self.node)['map_id']!=scope['map_id']:raise ValueError('地图已经改变，请重新查找')
                else:self.update(mode='found' if hits else 'not_found',hits=hits,selected_object_id=hits[0]['id'] if len(hits)==1 else None,message=describe_entities(query,hits))
        except Exception as exc:self.update(mode='failed',hits=[],selected_object_id=None,message='查找未完成：'+str(exc))
        self.speak(self.state['message'])
    def answer(self,query=None):
        with self.lock:
            if self.active():
                if self.state.get('mode')=='searching':return self.state['message']
                raise ValueError('请先停止当前任务再查询物品位置')
            query=(query or self.state.get('query') or '').strip()
            if not query:return '还没有查找记录，请说帮我找，再加物品名称。'
            if not 1<=len(query)<=40:raise ValueError('请输入简短物体名称')
            scope=current_scope(self.node)
            # Clear old selection before I/O, including failures and empty new queries.
            self.update(source='semantic',mode='searching',query=query,map_id=scope['map_id'],hits=[],selected_object_id=None,target=None)
            try:
                hits=self.memory_objects(query,scope)
                if current_scope(self.node)['map_id']!=scope['map_id']:raise ValueError('地图已经改变，请重新查询')
                message=describe_entities(query,hits)
                self.update(mode='found' if hits else 'not_found',hits=hits,selected_object_id=hits[0]['id'] if len(hits)==1 else None,message=message)
                return message
            except Exception:
                self.update(mode='failed',message='暂时无法读取物体记忆，请稍后再试')
                raise
