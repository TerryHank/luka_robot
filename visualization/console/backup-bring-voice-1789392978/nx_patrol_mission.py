"""One-pass patrol and recorded-object search, with explicit cancellation."""
import json,time,threading,urllib.request,urllib.error
from pathlib import Path
from nx_object_target import target_from_job

ROUTE=[('wp_008','厨房'),('wp_009','卧室'),('wp_010','浴室')]

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
        self.path=Path(root or '/home/sunrise/luka_ws/patrol_mission.json')
        self.lock=threading.RLock();self.cancel=threading.Event();self.thread=None
        self.state={'mode':'idle','message':'巡航待命','route':[n for _,n in ROUTE], 'hits':[]}
        interrupted=False
        try:
            self.state.update(json.loads(self.path.read_text()))
            if self.state['mode'] in ('patrolling','searching','stopping','bringing','verifying'):
                self.state.update(mode='interrupted',message='服务重启中断任务，不自动续航；已有录像保留')
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
            rec=vision('/patrol/status')['recording']
            if rec and rec['id']==self.state.get('session'):vision('/patrol/stop',{})
            vision('/patrol/cancel',{})
            self.update(mode='interrupted',message='重启后的巡航已取消，已保存录像；不会自动续航')
        except Exception as exc:self.update(mode='failed',message='重启恢复未完成，请手动停止导航：'+str(exc))
    def update(self,**kw):
        with self.lock:
            self.state.update(kw);self.state['updated_at']=time.time()
            temp=self.path.with_suffix('.tmp');temp.write_text(json.dumps(self.state,ensure_ascii=False));temp.replace(self.path)
    def snapshot(self):
        with self.lock:return dict(self.state)
    def active(self):return self.thread is not None and self.thread.is_alive()
    def target(self,body=None):
        body=body or {};status=vision('/patrol/status');job=status.get('job') or {}
        if body.get('job_id'):
            session=body.get('session','')
            import re
            if not re.fullmatch('[a-f0-9]{32}',session):raise ValueError('无效录像编号')
            jobs=vision('/patrol/searches?session='+session)
            job=next((j for j in jobs if j['id']==body['job_id']),{})
        return target_from_job(job,self.node.current_floor_id,self.node.map_info)
    def bring(self,body):
        if self.active() and self.state['mode']=='searching':
            self.stop();self.thread.join(6)
        with self.lock:
            if self.active() or self.node.nx_handle is not None:raise ValueError('请先停止当前巡航、导航或查找')
            if self.node.relocalization.running:raise ValueError('请先完成定位')
            now=time.monotonic()
            if not self.node.pose or now-self.node.last['pose']>1 or now-self.node.last['scan']>1:
                raise ValueError('当前定位或雷达数据过期')
            target=self.target(body)
            status=vision('/patrol/status')
            if status.get('recording') or (status.get('job') or {}).get('status')=='searching':raise ValueError('请先结束录像或查找')
            vision('/model/unload',{})
            self.cancel.clear();self.update(mode='bringing',message='正在前往'+target['display_name'],target=target)
            self.thread=threading.Thread(target=self.run_bring,args=(target,),daemon=True);self.thread.start()
            return dict(ok=True,message='带你去'+target['query']+'的观察位置，到达后再确认。')
    def run_bring(self,target):
        try:
            with self.lock:
                if self.cancel.is_set():return
                self.send_observation(target)
            deadline=time.monotonic()+240
            while not self.cancel.wait(.2):
                if self.node.nx_nav_outcome is not None:break
                if time.monotonic()>deadline:raise ValueError('前往观察位置超时')
            if self.cancel.is_set():raise ValueError('已取消带路')
            if self.node.nx_nav_outcome!=4:raise ValueError('导航取消或失败，未到达观察位置')
            self.stop_nav();self.update(mode='verifying',message='已到观察位置，正在重新确认'+target['query'])
            if self.cancel.wait(1):raise ValueError('已取消确认')
            r=self.node.relocalization
            if not r.still_since or time.monotonic()-r.still_since<.7 or time.monotonic()-r.odom_at>1:raise ValueError('小车未停稳，暂不确认物体')
            started=time.time();vision('/locate',{'query':target['query']});deadline=time.monotonic()+90
            while not self.cancel.wait(.5):
                health=vision('/health')
                if not health.get('busy'):
                    if health.get('error'):raise ValueError(health['error'])
                    result=health.get('result') or {}
                    if result.get('query')!=target['query'] or result.get('captured_at',0)<started-1:raise ValueError('未收到本次重新识别的结果')
                    found=bool(result.get('detections'))
                    text=('到达后再次看到了'+target['query']+'候选，请看相机画面确认。' if found else '已到观察位置，但这次没看到'+target['query']+'，可能移走或被遮挡了。')
                    self.update(mode='verified_candidate' if found else 'not_visible',message=text);self.speak(text);return
                if time.monotonic()>deadline:raise ValueError('到达后的视觉确认超时')
            raise ValueError('已取消确认')
        except Exception as exc:
            self.update(mode='cancelled' if self.cancel.is_set() else 'failed',message=str(exc));self.speak(str(exc))
        finally:
            try:self.stop_nav()
            except Exception:pass
            if self.state['mode']=='bringing':self.update(mode='cancelled',message='带路已取消')
    def route_snapshot(self):
        with self.lock:return self.route_store.snapshot()
    def save_route(self,body):
        with self.lock:
            if self.active():raise ValueError('请先停止当前任务再修改巡航路线')
            return self.route_store.save(body)
    def start(self,body=None):
        with self.lock:
            if self.active():raise ValueError('已有巡航或查找任务，请先停止')
            n=self.node;now=time.monotonic()
            if n.nx_handle is not None or n.relocalization.running:raise ValueError('请先结束当前导航或定位')
            if not n.pose or now-n.last['pose']>1:raise ValueError('请先完成并核对地图定位')
            if n.current_floor_id!='floor_4':raise ValueError('巡航路线仅适用于四楼')
            if now-n.last['scan']>1:raise ValueError('雷达数据过期')
            route=self.route_store.document()
            if body and 'revision' in body and body['revision']!=route['revision']:raise ValueError('路线已改变，请刷新并核对后启动')
            points=self.route_store.resolve(route)
            status=vision('/patrol/status')
            if status['recording'] or (status.get('job') or {}).get('status')=='searching':raise ValueError('录像或识别正在使用相机服务')
            vision('/model/unload',{})
            self.cancel.clear();self.update(mode='patrolling',message='正在开启录像',hits=[],leg=None,session=None,route=[p['display_name'] for p in points],route_revision=route['revision'])
            self.thread=threading.Thread(target=self.run_patrol,args=(route,points),daemon=True);self.thread.start()
            return dict(ok=True,message='开始巡航录像，依次前往'+'、'.join(p['display_name'] for p in points)+'。')
    def stop(self):
        self.cancel.set()
        with self.lock:
            self.stop_nav()
            if self.active():self.update(message='正在停止任务并保存录像')
        return dict(ok=True,message='已请求停止，正在保存已有录像。')
    def run_patrol(self,route,points):
        session=None
        try:
            session=vision('/patrol/start',{})['id'];self.update(session=session)
            # Ensure capture actually opened before permitting motion.
            if self.cancel.wait(.5):return
            record=vision('/patrol/status')['recording']
            if not record or record['id']!=session or record.get('frames',0)<1:raise ValueError('录像未正常开始')
            for index,point in enumerate(points):
                ident,name=point['id'],point['display_name']
                with self.lock:
                    if self.cancel.is_set():break
                    current=self.route_store.resolve(route)
                    if current!=points:raise ValueError('航点位置或名称已改变，请重新核对路线')
                    self.update(leg=ident,leg_index=index+1,message=f'巡航录像 {index+1}/{len(points)}：前往'+name)
                    self.send(ident)
                deadline=time.monotonic()+240;last_check=0
                while not self.cancel.wait(.2):
                    if self.node.nx_nav_outcome is not None:break
                    if time.monotonic()>deadline:raise ValueError(name+'导航超时')
                    if time.monotonic()-last_check>2:
                        rec=vision('/patrol/status')['recording'];last_check=time.monotonic()
                        if not rec or rec['id']!=session:raise ValueError('录像已中断')
                if self.cancel.is_set():break
                if self.node.nx_nav_outcome!=4:raise ValueError('导航取消、接管或失败，已结束巡航')
                self.update(message='已到'+name+'，停留录像')
                if self.cancel.wait(route['dwell_s']):break
            self.update(mode='cancelled' if self.cancel.is_set() else 'complete',message='巡航已停止，录像已保存' if self.cancel.is_set() else '巡航完成，录像已保存')
        except Exception as exc:self.update(mode='failed',message='巡航已结束：'+str(exc))
        finally:
            try:self.stop_nav()
            except Exception as exc:self.update(message=self.state['message']+'；停车确认失败：'+str(exc))
            if session:
                try:
                    rec=vision('/patrol/status')['recording']
                    if rec and rec['id']==session:vision('/patrol/stop',{})
                except Exception as exc:self.update(message=self.state['message']+'；录像收尾待确认：'+str(exc))
            if self.state['mode']=='patrolling':self.update(mode='cancelled',message='巡航已停止，已保存录像')
            self.speak(self.state['message'])
    def search(self,query):
        if not isinstance(query,str) or not 1<=len(query.strip())<=40:raise ValueError('请输入简短物体名称')
        if self.active() and self.state['mode']=='patrolling':
            self.stop();self.thread.join(6)
        with self.lock:
            if self.active():raise ValueError('已有任务正在收尾或查找，请稍后再试')
            if self.node.nx_handle is not None:raise ValueError('请先停止导航再查找')
            status=vision('/patrol/status')
            if status['recording']:raise ValueError('请先停止录像')
            if (status.get('job') or {}).get('status')=='searching':raise ValueError('已有录像搜索进行中')
            sessions=[s for s in status['sessions'] if s['status'] in ('complete','interrupted') and s.get('keyframes',0)>0]
            if not sessions:raise ValueError('还没有可查找的录像，请先巡航录像')
            self.stop_nav();self.cancel.clear()
            self.update(mode='searching',query=query.strip(),message='正在按时间从新到旧查找录像',hits=[],searched=0,total_sessions=len(sessions))
            self.thread=threading.Thread(target=self.run_search,args=(sessions,query.strip()),daemon=True);self.thread.start()
            return dict(ok=True,message='正在录像中查找'+query+'，找到后会告诉你。')
    def run_search(self,sessions,query):
        try:
            for index,session in enumerate(sessions):
                if self.cancel.is_set():break
                job=vision('/patrol/search',dict(session=session['id'],query=query))
                deadline=time.monotonic()+1800
                while not self.cancel.wait(1):
                    current=vision('/patrol/status').get('job') or {}
                    if current.get('id')!=job['id']:raise ValueError('搜索任务被替换')
                    self.update(message=f'正在查找{query}：录像 {index+1}/{len(sessions)}，画面 {current["done"]}/{current["total"]}')
                    if current['status']!='searching':break
                    if time.monotonic()>deadline:raise ValueError('本段录像检索超时')
                if self.cancel.is_set():vision('/patrol/cancel',{});break
                if current['status']!='complete':raise ValueError(current.get('error') or '搜索未完成')
                hits=[dict(h,session=session['id']) for h in current['hits']]
                self.update(searched=index+1)
                if hits:
                    first=hits[0]
                    self.update(mode='found',hits=hits,message=f'录像第{round(first["seconds"])}秒发现{query}候选，请看截图确认。')
                    self.speak(self.state['message']);return
            self.update(mode='cancelled' if self.cancel.is_set() else 'not_found',message='查找已停止' if self.cancel.is_set() else '已搜索现有录像，暂未发现'+query+'。没检出不代表物品不在。')
        except Exception as exc:
            try:vision('/patrol/cancel',{})
            except Exception:pass
            self.update(mode='failed',message='查找未完成：'+str(exc))
        self.speak(self.state['message'])
