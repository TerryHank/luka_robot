#!/usr/bin/env python3
"""S100 dashboard with the migrated NX controls and S100 service management."""
import urllib.request
from nx_people_proxy import handle as people_handle
from pathlib import Path
from pathlib import Path as _SourcePath
import sys as _source_sys
_source_root = _SourcePath(__file__).resolve().parents[2]
for _package_path in ['system/luka_capabilities', 'behavior/luka_behaviors', 'mission/luka_mission']:
    _source_dir = _source_root / _package_path
    if _source_dir.is_dir() and str(_source_dir) not in _source_sys.path:
        _source_sys.path.insert(0, str(_source_dir))
from luka_behaviors.registry import BehaviorRegistry
from object_pose_context import ObjectPoseContext
from s100_function_start import FunctionStart
from luka_mission.manager import MissionManager
from nx_patrol_route import PatrolRoute
from nx_assistant_tools import execute as execute_assistant, TOOLS as ASSISTANT_TOOLS
from nx_music import Music
from nx_runtime_health import RuntimeHealth
from nx_product_api import ProductAPI
from nx_destination_catalog import customer_destinations
from s100_boot_pose import save_verified_pose, navigation_verified
from sensor_msgs.msg import Joy
from urllib.parse import urlparse, parse_qs
import math, time, threading, secrets
import os, subprocess
from std_srvs.srv import Empty, SetBool
import lightweight_robot_dashboard as app
from web_teleop_dashboard import WebTeleop
from nx_escape_recovery import EscapeRecovery

original_post = app.Handler.do_POST
original_get = app.Handler.do_GET
original_init = app.DashboardNode.__init__
function_start=FunctionStart()
static_localization_lock=threading.Lock()

def start_static_localization_check(node):
    def check():
        if not static_localization_lock.acquire(blocking=False):
            return
        try:
            # Let the old map->odom transform expire after the AMCL restart.
            # This path only submits an initial pose and never rotates the car.
            time.sleep(2)
            script=Path(__file__).with_name('s100_boot_localize.py')
            result=subprocess.run(['/usr/bin/python3',str(script),'--static-only'],
                                  capture_output=True,text=True,timeout=150)
            output=(result.stdout+' '+result.stderr).strip()[-300:]
            node.get_logger().info('Static localization check: exit=%d %s'%(result.returncode,output))
        except Exception as exc:
            node.get_logger().warn('Static localization check failed: '+str(exc)[:200])
        finally:
            static_localization_lock.release()
    threading.Thread(target=check,daemon=True).start()

def init(self):
    original_init(self)
    # NX uses encoder odometry; the migrated UI's /odometry/filtered is absent.
    self.create_subscription(app.Odometry,'/wheel/odom',self.on_odom,app.qos_profile_sensor_data)
    candidates = [m for m in self.available_maps if m['floor_id'] == 'floor_4']
    if candidates:
        self.select_map(candidates[0]['id'])
    self.nx_voice_pub=self.create_publisher(app.String,'/voice/control',10)
    self.object_pose_context=ObjectPoseContext(self)
    self.behaviors=BehaviorRegistry(self,lambda:destination_catalog(self),navigation_verified)
    self.relocalization=self.behaviors.relocalize.legacy_controller
    self.create_timer(5.0,lambda:save_verified_pose(self))
    self.nx_speech_pub=self.create_publisher(app.String,'/llm_status',10)
    self.missions=MissionManager(self,self.behaviors,lambda text:speak_nav(self,text))
    self.patrol_mission=self.missions.patrol
    self.product=ProductAPI(self)
    self.raw_localization_status=self.product.localization_status
    self.product.localization_status=lambda:verified_localization_status(self)
    self.assistant_generation=secrets.randbits(48)
    self.assistant_lock=threading.RLock()
    self.music=Music()
    self.function_start=function_start
    self.function_start.relocalize=lambda:start_static_localization_check(self)
    self.runtime_health=RuntimeHealth(self)
    legacy_diagnostics=self.diagnostics.snapshot
    self.diagnostics.snapshot=lambda:s100_diagnostics(self,legacy_diagnostics)
    self.behaviors.initialize_follow()
    self.follow_controller=self.behaviors.follow.legacy_controller
    self.follow_acquisition=self.behaviors.follow.acquisition
    self.patrol_mission.route_store=PatrolRoute('/home/sunrise/luka_ws/common/state/patrol_route.json',lambda:destination_catalog(self),lambda:self.current_floor_id)
    self.product.navigate=lambda target:send_nav(self,None,target)
    self.patrol_mission.send_observation=lambda target:send_nav(self,None,target)
    self.create_subscription(Joy,'/joy',lambda msg:setattr(self,'assistant_generation',self.assistant_generation+1) if len(msg.buttons)>4 and msg.buttons[4] else None,app.qos_profile_sensor_data)
    self.create_subscription(Joy,'/joy',lambda msg:self.patrol_mission.cancel.set() if len(msg.buttons)>4 and msg.buttons[4] and self.patrol_mission.active() else None,app.qos_profile_sensor_data)
    if os.getenv('LUKA_SOFTWARE_ONLY') == '1':
        self.web_teleop=WebTeleop(self,lambda:stop_nav(self,wait_for_gate=False))
        self.escape_recovery=EscapeRecovery(self)
        threading.Thread(target=refresh_static_localization,args=(self,),daemon=True).start()

def s100_diagnostics(node, legacy_snapshot):
    """Show S100's live topics instead of NX-only health expectations."""
    legacy=legacy_snapshot()
    current=node.runtime_health.snapshot()
    checks=[]
    for item in current['checks']:
        age=item.get('age_s')
        detail=(str(age)+'秒前收到') if age is not None and item['ready'] else item['reason']
        checks.append({'label':item['name'],'ok':item['ready'],'detail':detail})
    for item in legacy['checks']:
        if item['label'] in ('融合','IMU转速','bt_navigator','planner_server','controller_server'):
            checks.append(item)
    checks.append({'label':'相机与人体识别','ok':None,'detail':'实时画面年龄和识别帧率见「人体识别」工作区'})
    return {'checks':checks,'latest_incident':legacy.get('latest_incident')}

def verified_localization_status(node):
    status=node.raw_localization_status()
    status['navigation_verified']=navigation_verified(status)
    if status.get('ready') and not status['navigation_verified']:
        status['ready']=False
        status['reason']='已有位置候选，但角落扫描或重复定位尚未通过核验；等待自动重定位'
    elif status['navigation_verified'] and not status.get('running'):
        status['message']='定位已通过雷达与地图核验；移动前仍请留意周围环境'
    return status

def refresh_static_localization(node):
    # A stationary AMCL need not republish /amcl_pose when only the dashboard
    # restarts; request its existing no-motion update so NX's gate can assess it.
    for _ in range(8):
        if node.relocalization.pose_at:return
        if node.relocalization.update_client.service_is_ready():
            node.relocalization.update_client.call_async(Empty.Request())
        time.sleep(1)






def send_nav(self,poi_id,observation=None):
    return self.behaviors.navigate.start(poi_id,observation=observation)

def stop_nav(self,wait_for_gate=True):
    return self.behaviors.navigate.cancel(wait_for_gate=wait_for_gate)

def speak_nav(self,text):
    from luka_behaviors.navigation_execution import speak_nav as speak
    return speak(self,text)

def destination_catalog(node):
    custom=customer_destinations(node.product.store,node.current_floor_id)
    names={r['display_name'] for r in custom}
    legacy=[dict(r,floor_id=node.current_floor_id,source='legacy') for r in node.load_waypoints() if r['display_name'] not in names]
    return custom+legacy


def post(self):
    path=self.path.split('?',1)[0]
    if path in ('/api/live-object/start','/api/live-object/stop'):
        try:
            origin=self.headers.get('Origin')
            if origin and urlparse(origin).netloc!=self.headers.get('Host'):raise ValueError('请从小车监控页面操作')
            size=int(self.headers.get('Content-Length','0'))
            if not 0<=size<=1024:raise ValueError('请求过大')
            body=self.rfile.read(size)
            endpoint='/start' if path.endswith('/start') else '/stop'
            request=urllib.request.Request('http://127.0.0.1:8099'+endpoint,data=body or b'{}',headers={'Content-Type':'application/json'},method='POST')
            try:
                with urllib.request.urlopen(request,timeout=5) as response:
                    return self.send_json(app.json.loads(response.read()),response.status)
            except urllib.error.HTTPError as exc:
                return self.send_json(app.json.loads(exc.read()),exc.code)
        except ValueError as exc:return self.send_json({'error':str(exc)},400)
        except Exception as exc:return self.send_json({'error':'YOLOE‑26n 实时检索服务不可用：'+str(exc)},503)
    if os.getenv('LUKA_SOFTWARE_ONLY') == '1':
        path=self.path.split('?',1)[0]
        if path.startswith('/api/teleop/'):
            return app.NODE.web_teleop.handle_post(self,path)
    if self.path.split('?',1)[0]=='/api/people/stop':app.NODE.follow_controller.stop('人体识别已停止')
    if self.path.split('?',1)[0].startswith('/api/people/'):return people_handle(self,post=True)
    if self.path.startswith("/product/api/"):return app.NODE.product.handle(self,post=True)
    path=self.path.split('?',1)[0]
    if path in ('/api/follow/start','/api/follow/stop','/api/follow/choose'):
        try:
            origin=self.headers.get('Origin')
            if origin and urlparse(origin).netloc!=self.headers.get('Host'):raise ValueError('请从小车监控页面操作')
            if path.endswith('/choose'):
                size=int(self.headers.get('Content-Length',0))
                if not 0<=size<=1024:raise ValueError('请求过大')
                body=app.json.loads(self.rfile.read(size) or b'{}')
                if not isinstance(body,dict):raise ValueError('请求格式无效')
                result=app.NODE.follow_acquisition.choose(body.get('mode'),body.get('id'))
            elif path.endswith('/start'):
                result=app.NODE.follow_controller.start()
            else:
                app.NODE.follow_acquisition.cancel()
                result=app.NODE.follow_controller.stop()
            return self.send_json(dict(ok=True,**result))
        except Exception as exc:return self.send_json({'error':str(exc)},409)
    if path=='/api/music':
        try:
            origin=self.headers.get('Origin')
            if origin and urlparse(origin).netloc!=self.headers.get('Host'):raise ValueError('来源校验失败')
            size=int(self.headers.get('Content-Length',0))
            if not 0<=size<=8192:raise ValueError('请求过大')
            body=app.json.loads(self.rfile.read(size) or b'{}');action=body.get('action')
            if action not in ('search','play','pause','resume','stop','status','volume'):raise ValueError('不支持的音乐操作')
            return self.send_json({'ok':True,'message':app.NODE.music.action(action,body),'volume':app.NODE.music.volume})
        except Exception as exc:return self.send_json({'error':str(exc)},400)
    if path=='/api/assistant/execute':
        try:
            origin=self.headers.get('Origin')
            if origin and urlparse(origin).netloc!=self.headers.get('Host'):raise ValueError('请从小车网页操作')
            size=int(self.headers.get('Content-Length',0))
            if not 0<=size<=8192:raise ValueError('请求过大')
            body=app.json.loads(self.rfile.read(size) or b'{}')
            tool=body.get('tool')
            def run():return execute_assistant(app.NODE,tool,body.get('arguments',{}),body.get('source',''),destination_catalog,send_nav,app.NODE.music)
            if tool in ('navigate','patrol_start','object_bring','localization_auto','cancel_all','patrol_stop','follow_start','follow_stop'):
                with app.NODE.assistant_lock:
                    if tool in ('cancel_all','patrol_stop','follow_stop'):app.NODE.assistant_generation+=1
                    elif body.get('generation')!=app.NODE.assistant_generation:raise ValueError('指令已因停车或接管失效，请重新发出指令')
                    message=run()
            else:message=run()
            return self.send_json({'ok':True,'message':message})
        except Exception as exc:return self.send_json({'error':str(exc)},400)
    if path in ('/api/patrol/start','/api/patrol/stop','/api/patrol/find','/api/patrol/bring','/api/patrol/route',
                '/api/patrol/nav-test/start','/api/patrol/nav-test/stop'):
        try:
            origin=self.headers.get('Origin')
            if origin and urlparse(origin).netloc!=self.headers.get('Host'):raise ValueError('请从小车前端操作')
            size=int(self.headers.get('Content-Length',0))
            if not 0<=size<=4096:raise ValueError('请求过大')
            body=app.json.loads(self.rfile.read(size) or b'{}')
            mission=app.NODE.patrol_mission
            if path.endswith('/stop'):
                with app.NODE.assistant_lock:app.NODE.assistant_generation+=1
            result=(mission.start_nav_test(body) if path=='/api/patrol/nav-test/start'
                    else mission.save_route(body) if path.endswith('/route')
                    else mission.start(body) if path.endswith('/start')
                    else mission.stop() if path.endswith('/stop')
                    else mission.bring(body) if path.endswith('/bring')
                    else mission.search(body.get('query')))
            self.send_json(result,202)
        except Exception as exc:self.send_json({'error':str(exc)},400)
        return
    if path in ('/api/nav','/api/localization/manual','/api/localization/auto','/api/map/select') and app.NODE.patrol_mission.active():
        self.send_json({'error':'请先停止当前巡航或查找任务'},409);return
    if self.path.split('?',1)[0] in ('/api/localization/manual','/api/localization/auto'):
        try:
            origin=self.headers.get('Origin')
            if origin and urlparse(origin).netloc!=self.headers.get('Host'):raise ValueError('请从小车网页操作')
            size=int(self.headers.get('Content-Length',0))
            if size<0 or size>4096:raise ValueError('请求过大')
            body=app.json.loads(self.rfile.read(size) or b'{}')
            mode=self.path.split('?',1)[0].rsplit('/',1)[-1]
            # Relocalization.stop_nav() acquires nx_lock itself; holding it here
            # would deadlock the automatic localization request.
            result=app.NODE.relocalization.start(mode,body)
            app.NODE.nx_status='定位操作中，导航已停止'
            self.send_json(result,202)
        except (ValueError,KeyError,TypeError) as exc:self.send_json({'error':str(exc)},400)
        except Exception as exc:self.send_json({'error':str(exc)},503)
        return
    if self.path.split('?',1)[0] in ('/api/functions/start','/api/functions/restart'):
        origin=self.headers.get('Origin')
        if origin and urlparse(origin).netloc!=self.headers.get('Host'):
            self.send_json({'error':'请从小车网页点击启动'},403);return
        restart=self.path.split('?',1)[0]=='/api/functions/restart'
        if restart or not function_start.status()['all_active']:
            stop_nav(app.NODE)
            if hasattr(app.NODE,'web_teleop'):app.NODE.web_teleop.force_stop()
            app.NODE.follow_controller.stop('功能正在启动或重启')
            app.NODE.relocalization.stop_rotation()
            with app.NODE.assistant_lock:
                app.NODE.assistant_generation+=1
                app.NODE.patrol_mission.stop()
            app.NODE.nx_status='正在重启功能，完成后请检查定位并重新选择目标' if restart else '正在启动功能，请检查定位'
        self.send_json(function_start.start(restart=restart),202);return
    if self.path.split('?',1)[0] in ('/api/voice/wake','/api/voice/test'):
        if app.NODE.nx_voice_pub.get_subscription_count()==0:
            self.send_json({'error':'语音服务未就绪，请在监控页检查语音服务状态'},503)
        else:
            command='test_wake' if self.path.split('?',1)[0]=='/api/voice/test' else 'wake'
            app.NODE.nx_voice_pub.publish(app.String(data=command))
            self.send_json({'ok':True,'message':'已进入聆听，请直接说指令'})
        return
    if self.path.split('?',1)[0]=='/api/nav/stop':
        try:
            stop_nav(app.NODE)
            if hasattr(app.NODE,'web_teleop'):app.NODE.web_teleop.force_stop()
            app.NODE.follow_controller.stop('已停车')
            app.NODE.relocalization.stop_rotation()
            with app.NODE.assistant_lock:
                app.NODE.assistant_generation+=1
                app.NODE.patrol_mission.stop()
            app.NODE.nx_status='已停止导航'
            self.send_json({'ok':True})
        except Exception as exc:self.send_json({'error':str(exc)},503)
        return
    # Explicit natural-language requests are dispatched through validated NX tools.
    if self.path.split('?', 1)[0] not in ('/api/map/select', '/api/llm', '/api/nav', '/api/nav/mode', '/api/waypoints'):
        self.send_json({'error': '此操作尚未迁移到 S100'}, 409)
        return
    original_post(self)

def get(self):
    path=self.path.split('?',1)[0]
    if path in ('/api/live-object/status','/api/live-object/classes','/api/live-object/frame.jpg'):
        endpoint=path.removeprefix('/api/live-object')
        try:
            with urllib.request.urlopen('http://127.0.0.1:8099'+endpoint,timeout=4) as response:
                data=response.read(2_000_000)
                if endpoint=='/frame.jpg':return self.send_bytes(data,'image/jpeg')
                return self.send_json(app.json.loads(data))
        except urllib.error.HTTPError as exc:
            return self.send_json({'error':'实时检索画面尚未就绪' if exc.code==503 else str(exc)},exc.code)
        except Exception as exc:return self.send_json({'error':'YOLOE‑26n 实时检索服务不可用：'+str(exc)},503)
    if self.path.split('?',1)[0]=='/api/teleop/status' and os.getenv('LUKA_SOFTWARE_ONLY') == '1':
        return self.send_json(app.NODE.web_teleop.status())
    if self.path.split('?',1)[0]=='/api/follow/status':return self.send_json(dict(app.NODE.follow_controller.snapshot(),acquisition=app.NODE.follow_acquisition.status()))
    if self.path.split('?',1)[0].startswith('/api/people/'):return people_handle(self)
    if self.path.split('?',1)[0]=='/assistant-help':return self.send_bytes(Path(__file__).with_name('ASSISTANT_MUSIC.md').read_bytes(),'text/plain; charset=utf-8')
    if self.path.split('?',1)[0]=='/music-ui.js':return self.send_bytes(Path(__file__).with_name('nx_music_ui.js').read_bytes(),'application/javascript; charset=utf-8')
    if self.path.split('?',1)[0]=='/api/music':return self.send_json({'message':app.NODE.music.action('status',{}),'volume':app.NODE.music.volume})
    if self.path.split('?',1)[0]=='/api/assistant/tools':return self.send_json({'tools':ASSISTANT_TOOLS,'generation':app.NODE.assistant_generation})
    if self.path.split('?',1)[0]=='/voiceprint-ui.js':return self.send_bytes(Path(__file__).with_name('nx_voiceprint_ui.js').read_bytes(),'application/javascript; charset=utf-8')
    if self.path.split('?',1)[0]=='/patrol-route.js':return self.send_bytes(Path(__file__).with_name('nx_patrol_route.js').read_bytes(),'application/javascript; charset=utf-8')
    if self.path.split('?',1)[0]=='/api/patrol/route':
        try:return self.send_json(app.NODE.patrol_mission.route_snapshot())
        except Exception as exc:return self.send_json({'error':str(exc)},400)
    if self.path.split("?",1)[0]=="/api/voice/destinations":return self.send_json({"floor_id":app.NODE.current_floor_id,"destinations":destination_catalog(app.NODE)})
    if self.path.split("?",1)[0]=="/api/sonar/status":return self.send_json(app.NODE.product.sonar_status())
    if self.path.startswith("/product/api/"):return app.NODE.product.handle(self)
    if self.path.split("?",1)[0] in ("/product","/product/"):
        return self.send_bytes(Path(__file__).with_name("nx_product.html").read_bytes(),"text/html; charset=utf-8")
    if self.path.split('?',1)[0] in ('/user','/user/'):
        self.send_bytes(Path(__file__).with_name('nx_product.html').read_bytes(),'text/html; charset=utf-8');return
    if self.path.split('?',1)[0]=='/api/patrol/target':
        try:self.send_json(dict(ok=True,target=app.NODE.patrol_mission.target()))
        except Exception as exc:self.send_json({'ok':False,'error':str(exc)})
        return
    if self.path.split('?',1)[0]=='/api/patrol/status':
        self.send_json(app.NODE.patrol_mission.snapshot());return
    if self.path.split('?',1)[0]=='/api/localization/status':
        self.send_json(app.NODE.product.localization_status());return
    if self.path.split('?',1)[0]=='/api/localization/candidate':
        self.send_json(app.NODE.raw_localization_status());return
    if self.path.split('?',1)[0]=='/api/functions/status':
        self.send_json(dict(function_start.status(),health=app.NODE.runtime_health.snapshot()));return
    if self.path.split('?',1)[0]=='/api/object/pose':
        try:
            stamp=float(parse_qs(urlparse(self.path).query)['stamp'][0])
            if not math.isfinite(stamp):raise ValueError('invalid timestamp')
            self.send_json(app.NODE.object_pose_context.snapshot(stamp))
        except (KeyError,ValueError) as exc:self.send_json({'error':str(exc)},400)
        return
    if self.path.split('?',1)[0]=='/help':
        try:self.send_bytes(Path('/home/sunrise/luka_ws/docs/legacy/NX使用说明.html').read_bytes(),'text/html; charset=utf-8')
        except OSError:self.send_json({'error':'说明文件暂不可用'},503)
        return
    if self.path.split('?',1)[0]=='/api/nav/state':
        self.send_json({'status':app.NODE.nx_status});return
    if self.path.split('?', 1)[0] == '/camera.jpg':
        try:
            with urllib.request.urlopen('http://127.0.0.1:8091/preview.jpg', timeout=3) as response:
                self.send_bytes(response.read(), 'image/jpeg')
        except Exception:
            self.send_json({'error': '相机暂不可用'}, 503)
        return
    original_get(self)

app.DashboardNode.__init__ = init
app.DashboardNode.send_nav=send_nav
app.Handler.do_POST = post
app.Handler.do_GET = get
app.HTML = app.HTML.replace('解析测试','指令执行')
app.HTML = app.HTML.replace('Robot Monitor', 'NX 小车导航')
app.HTML=app.HTML.replace('<header>',Path(__file__).with_name('nx_people_ui.html').read_text(encoding='utf-8')+'<header>',1)
app.HTML=app.HTML.replace('</body>','<script>'+Path(__file__).with_name('nx_people_ui.js').read_text(encoding='utf-8')+'</script></body>')
app.HTML=app.HTML.replace('</body>','<script>'+Path(__file__).with_name('nx_follow_ui.js').read_text(encoding='utf-8')+'</script></body>')
app.HTML = app.HTML.replace('<header>', '<div style="padding:8px;background:#edf5ff"><button id="nxVoiceTest">测试语音识别（不执行动作）</button> 测试会保存本次语音片段用于排查，普通对话不新增音频保存。<span id="nxVoiceTestStatus"></span></div><header>',1)
app.HTML = app.HTML.replace('</body>', '''<script>document.getElementById('nxVoiceTest').onclick=async()=>{const s=document.getElementById('nxVoiceTestStatus');try{const r=await fetch('/api/voice/test',{method:'POST'});const d=await r.json();s.textContent=r.ok?'进入聆听后直接说一句话；本次只回读识别内容。':d.error;}catch(e){s.textContent='连接失败';}};</script></body>''')
app.HTML = app.HTML.replace('<header>', '<section style="padding:14px;background:#eaf5ef"><button id="nxStartAll" style="font-size:18px;padding:10px 20px;background:#176b45;color:white;border:0;border-radius:6px">一键启动小车功能</button> <button id="nxRestartAll" style="font-size:18px;padding:10px;background:#ae4c16;color:white;border:0;border-radius:6px">一键重启功能</button> <span id="nxStartState">正在读取服务状态…</span><div id="nxServices" style="margin-top:8px"></div><small>启动不会自动行驶；重启功能会先停车、结束录像并重载服务，不是整机重启。重启后需检查定位并重新选择导航目标。</small></section><header>',1)
app.HTML = app.HTML.replace('<header>', '<div id="nxMemory" style="padding:10px 14px;background:#e7eef6;color:#173451">正在读取 S100 实际内存…</div><header>',1)
app.HTML = app.HTML.replace('</body>', '''<script>
async function nxRefreshServices(){const b=document.getElementById('nxStartAll'),s=document.getElementById('nxStartState'),list=document.getElementById('nxServices');try{const r=await fetch('/api/functions/status');if(!r.ok)throw Error('状态读取失败');const d=await r.json();b.disabled=d.running;document.getElementById('nxRestartAll').disabled=d.running;b.textContent=d.running?'正在启动…':'一键启动小车功能';s.textContent=(d.all_active?'全部服务进程已启动。 ':'')+(d.error||d.message);if(d.health){const h=d.health;s.textContent+=' '+h.message+(h.warnings.length?'；'+h.warnings.join('；'):'');s.style.color=h.navigation_data_ready?'#176b45':'#a43b16';}list.replaceChildren();for(const x of d.services){const e=document.createElement('span');e.style.cssText='display:inline-block;margin:3px 12px 3px 0';e.textContent=(x.state==='active'?'● ':'○ ')+x.name+'：'+({'active':'运行中','inactive':'未启动','activating':'启动中','failed':'启动失败'}[x.state]||x.state);e.style.color=x.state==='active'?'#176b45':'#a43b16';list.append(e);}if(d.health){for(const c of d.health.checks){const e=document.createElement('span');e.style.cssText='display:inline-block;margin:3px 12px 3px 0';e.style.color=c.ready?'#176b45':'#a43b16';e.textContent=c.name+'：'+c.reason+(c.age_s!=null?'（'+c.age_s+'秒）':'');list.append(e);}}}catch(e){s.textContent='无法连接服务状态，请检查小车网络';}}
document.getElementById('nxStartAll').onclick=async()=>{const b=document.getElementById('nxStartAll');b.disabled=true;try{const r=await fetch('/api/functions/start',{method:'POST'});const d=await r.json();if(!r.ok)throw Error(d.error);document.getElementById('nxStartState').textContent=d.message;}catch(e){document.getElementById('nxStartState').textContent=e.message;}finally{await nxRefreshServices();}};
document.getElementById('nxRestartAll').onclick=async()=>{document.getElementById('nxRestartAll').disabled=true;document.getElementById('nxStartAll').disabled=true;try{const r=await fetch('/api/functions/restart',{method:'POST'});const d=await r.json();if(!r.ok)throw Error(d.error);document.getElementById('nxStartState').textContent=d.message;}catch(e){document.getElementById('nxStartState').textContent=e.message;}finally{await nxRefreshServices();}};
nxRefreshServices();setInterval(nxRefreshServices,3000);
</script></body>''')
app.HTML = app.HTML.replace('</body>', '''<script>
async function nxRefreshMemory(){const e=document.getElementById('nxMemory');try{const r=await fetch('/api/functions/status',{cache:'no-store'});if(!r.ok)throw Error('状态接口不可用');const m=(await r.json()).health?.resources;if(!m||!Number.isFinite(m.total_memory_mb))throw Error('内存数据暂不可用');const gib=v=>(v/1024).toFixed(2);e.textContent=`S100 物理内存：已用 ${gib(m.used_memory_mb)} / 总计 ${gib(m.total_memory_mb)} GiB（${m.memory_used_percent}%） · 可用 ${gib(m.available_memory_mb)} GiB · 缓存 ${gib(m.cache_memory_mb)} GiB · Swap ${m.swap_used_mb}/${m.swap_total_mb} MiB`;e.title='读取本机 /proc/meminfo；已用不含可回收缓存，可用包含可回收缓存。每 5 秒更新。';}catch(err){e.textContent='S100 内存数据暂不可用：'+err.message;}}
nxRefreshMemory();setInterval(nxRefreshMemory,5000);
</script></body>''')
app.HTML = app.HTML.replace('<header>', '<div style="padding:10px;background:#edf5ff"><button id="nxVoiceWake">手动唤醒露卡</button> <a href="/help" target="_blank">小车使用说明与全部指令</a> <span id="nxVoiceHint">语音已开放：去厨房／卧室／浴室、停止导航；先唤醒露卡。</span></div><header>', 1)
app.HTML = app.HTML.replace('</body>', '<script>document.getElementById("nxVoiceWake").onclick=async()=>{const e=document.getElementById("nxVoiceHint");try{const r=await fetch("/api/voice/wake",{method:"POST"});const s=await r.json();e.textContent=s.error||s.message;}catch(err){e.textContent="连接失败，请检查小车网络";}};</script></body>')
app.HTML = app.HTML.replace('<header>', '<div style="padding:10px;background:#174834;color:white">四楼导航已开放（前进最高 0.4 米/秒）：在航点列表点击前往；按 LB 接管会取消导航。网页文字框和语音现在会执行明确指令；试运行请勿输入移动命令。<button id="nxNavStop" style="background:#bc2525;color:white">停止导航</button> <span id="nxNavStatus"></span> <a style="color:white" href="http://192.168.3.251:8091/view">视觉与巡航录像</a> <a style="color:white" href="http://192.168.3.251:8091/memory">物体观察记忆</a></div><header>', 1)
app.HTML = app.HTML.replace('</body>', '<script>document.getElementById("nxNavStop").onclick=async()=>{const r=await fetch("/api/nav/stop",{method:"POST"});if(!r.ok)alert((await r.json()).error);};setInterval(async()=>{try{const s=await(await fetch("/api/nav/state")).json();document.getElementById("nxNavStatus").textContent=s.status;}catch(e){document.getElementById("nxNavStatus").textContent="连接中断，请刷新并检查小车";}},1000);</script></body>')
app.HTML = app.HTML.replace('</body>', '<script>for(const id of ["followStart","followStop","shutdown"]){const e=document.getElementById(id);if(e){e.disabled=true;e.title="此入口尚未迁移到 S100";}}</script></body>')

app.HTML=app.HTML.replace('const e=log[i],d=document.createElement', "const e=log[i];if((e.msg||'').startsWith('chat_sentence:'))continue;const d=document.createElement")
app.HTML=app.HTML.replace('<header>',Path(__file__).with_name('nx_localization_ui.html').read_text(encoding='utf-8')+'<header>',1)
app.HTML=app.HTML.replace('<header>',Path(__file__).with_name('nx_patrol_ui.html').read_text(encoding='utf-8')+'<header>',1)
app.HTML=app.HTML.replace('<b>巡航实时记忆与找物</b>',Path(__file__).with_name('nx_live_object_ui.html').read_text(encoding='utf-8')+'<b>巡航实时记忆与找物</b>',1)
app.HTML=app.HTML.replace('<header>','<header><a href="/user" style="padding:8px 14px;border:1px solid #718f5b;border-radius:8px;color:#c3ef8b">打开用户页面 ↗</a>',1)
app.HTML=app.HTML.replace('</body>','<script>'+Path(__file__).with_name('nx_localization_ui.js').read_text(encoding='utf-8')+'</script></body>')

app.HTML=app.HTML.replace('<header>',Path(__file__).with_name('nx_sonar_ui.html').read_text(encoding='utf-8')+'<header>',1)


app.HTML=app.HTML.replace('</head>','<style>'+Path(__file__).with_name('nx_console_layout.css').read_text(encoding='utf-8')+'</style></head>')
app.HTML=app.HTML.replace('</body>','<script>'+Path(__file__).with_name('nx_console_layout.js').read_text(encoding='utf-8')+'</script></body>')

if __import__('os').getenv('LUKA_SOFTWARE_ONLY') == '1':
    app.HTML = app.HTML.replace('NX 小车导航', 'S100 小车导航')
    app.HTML = app.HTML.replace('http://192.168.3.251:8091/', 'http://192.168.3.150:8091/')
    app.HTML = app.HTML.replace("img.src='http://192.168.3.251:8091'+", "img.src=location.protocol+'//'+location.hostname+':8091'+")
    app.HTML = app.HTML.replace("document.getElementById('camera').src='/camera.jpg?t='+Date.now()},1000);", "document.getElementById('camera').src='/camera.jpg?t='+Date.now()},200);")
    app.HTML = app.HTML.replace('四楼导航已开放（前进最高 0.4 米/秒）：在航点列表点击前往；按 LB 接管会取消导航。网页文字框和语音现在会执行明确指令；试运行请勿输入移动命令。', '四楼导航已开放（前进最高 0.4 米/秒）：在航点列表点击前往；网页摇杆接管会取消导航。')
    app.HTML = app.HTML.replace('</body>', '<style>'+Path(__file__).with_name('web_teleop_ui.css').read_text(encoding='utf-8')+'</style><script>'+Path(__file__).with_name('web_teleop_ui.js').read_text(encoding='utf-8')+'</script></body>')

if __name__ == '__main__':
    app.main()
