from pathlib import Path
import sys, pathlib, time, json, subprocess, threading, os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import cv2
from urllib.parse import urlparse, parse_qs
from patrol import Patrol
from s100_model_runtime import ModelRuntime
from rgbd_geometry import object_position
from orbbec_ros_camera import OrbbecRosCamera
from object_memory import ObjectMemory
from semantic_memory import SemanticMemory
from yoloe_bridge import detect_all as yoloe_detect_all
from yoloe_bridge import canonical as yoloe_canonical, locate as yoloe_locate, unload as yoloe_unload, loaded as yoloe_loaded
ROOT=pathlib.Path(__file__).resolve().parent
OUT=Path('/home/sunrise/luka_data/recordings/locateanything_trial_20260907/live_results'); OUT.mkdir(exist_ok=True)
camera_source = os.getenv('NX_CAMERA_SOURCE', 'orbbec_ros')
if camera_source != 'orbbec_ros':
    raise ValueError('Current visual runtime consumes Orbbec ROS RGB-D only')
camera = OrbbecRosCamera()
lock=threading.Lock()
state={'ready':True,'busy':False,'result':None,'error':None}
track_guard=threading.Lock()
track_stop=threading.Event()
track_state={'running':False,'query':'','frames':0,'recognized':0,'skipped':0,'last_detections':0,'error':None,'started_at':None,'interval_s':0.4}
track_history=[]
runtime=ModelRuntime(ROOT)
ALIASES={'鼠标':'computer mouse','打火机':'lighter','水杯':'cup','杯子':'cup','瓶子':'bottle','手机':'cell phone','电脑':'laptop','椅子':'chair','办公椅':'chair','键盘':'keyboard','书':'book','遥控器':'remote','人':'person','门':'door','窗户':'window','桌子':'table','柜子':'cabinet','衣柜':'wardrobe','冰箱':'refrigerator','沙发':'sofa','电视':'television','显示器':'monitor','背包':'backpack','包':'bag','鞋子':'shoe','眼镜':'glasses','钥匙':'keys','剪刀':'scissors','电风扇':'fan','空调':'air conditioner','箱子':'cardboard box','纸箱':'cardboard box','垃圾桶':'trash can','床':'bed','窗帘':'curtain'}
def locate_file(image,query,prefix):
    image=pathlib.Path(image); prefix=pathlib.Path(prefix)
    prepared=None
    frame=cv2.imread(str(image))
    if frame is not None:
        luminance=float(cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY).mean())
        if luminance<75:
            import numpy as np
            beta=max(0,min(55,int((90-luminance)*0.9)))
            frame=cv2.convertScaleAbs(frame,alpha=1.0,beta=beta)
            lut=((np.arange(256)/255.0)**(1/1.35)*255).clip(0,255).astype('uint8')
            frame=cv2.LUT(frame,lut)
            prepared=prefix.with_suffix('.input.png')
            prepared.parent.mkdir(parents=True,exist_ok=True)
            cv2.imwrite(str(prepared),frame)
            image=prepared
    try:
        # S100 uses the bounded BPU image API; unsupported queries fail explicitly.
        if yoloe_canonical(query) is not None:
            runtime.unload()
            try:
                result = yoloe_locate(image, query, prefix)
                if result is not None:
                    return result
            except Exception:
                pass
            yoloe_unload()
        else:
            yoloe_unload()
        return runtime.locate(image,ALIASES.get(query,query),prefix)
    finally:
        if prepared is not None:
            prepared.unlink(missing_ok=True)
patrol=Patrol(ROOT,camera,lock,locate_file)
memory=ObjectMemory(ROOT,camera,lock,locate_file,object_position)
semantic=SemanticMemory(ROOT,camera,lock,yoloe_detect_all,object_position,runtime.unload,yoloe_unload,yoloe_loaded)

def infer_frame(query,sample,prefix=OUT/'result'):
    image=sample[2].copy()
    # The camera can be very dark indoors. Lift only low-light frames before
    # OWL-ViT inference; normal exposures are left untouched.
    luminance=float(cv2.cvtColor(image,cv2.COLOR_BGR2GRAY).mean())
    if luminance<75:
        beta=max(0,min(55,int((90-luminance)*0.9)))
        image=cv2.convertScaleAbs(image,alpha=1.0,beta=beta)
        lut=((__import__('numpy').arange(256)/255.0)**(1/1.35)*255).clip(0,255).astype('uint8')
        image=cv2.LUT(image,lut)
    h,w=image.shape[:2]; image=cv2.resize(image,(round(w*448/max(h,w)),round(h*448/max(h,w))))
    cv2.imwrite(str(OUT/'input.png'),image)
    result=locate_file(OUT/'input.png',query,prefix)
    result.update(query=query,captured_at=sample[0],completed_at=time.time())
    return result

def infer(query,sample):
    try:
        result=infer_frame(query,sample)
        state['result']=result; state['error']=None
    except Exception as e: state['error']=str(e)
    finally: state['busy']=False; lock.release()

def _box_iou(a,b):
    ax1,ay1,ax2,ay2=a['box']; bx1,by1,bx2,by2=b['box']
    ix1,iy1=max(ax1,bx1),max(ay1,by1); ix2,iy2=min(ax2,bx2),min(ay2,by2)
    inter=max(0,ix2-ix1)*max(0,iy2-iy1)
    area_a=max(0,ax2-ax1)*max(0,ay2-ay1); area_b=max(0,bx2-bx1)*max(0,by2-by1)
    return inter/(area_a+area_b-inter) if area_a+area_b-inter else 0

def confirmed_tracking_detections(detections):
    if not track_history: return []
    confirmed=[]
    for detection in detections:
        matches=0
        for previous in track_history[-2:]:
            if any(item['label']==detection['label'] and _box_iou(item,detection)>=0.15 for item in previous):
                matches+=1
        if matches>=1: confirmed.append(detection)
    return confirmed

def render_tracking_result(detections):
    image=cv2.imread(str(OUT/'input.png'))
    if image is None: return
    for detection in detections:
        x1,y1,x2,y2=map(int,detection['box'])
        x1,y1=max(0,x1),max(0,y1); x2,y2=min(image.shape[1]-1,x2),min(image.shape[0]-1,y2)
        cv2.rectangle(image,(x1,y1),(x2,y2),(0,220,120),2)
        cv2.putText(image,f"{detection['label']} {detection['score']:.2f}",(x1,max(20,y1-6)),cv2.FONT_HERSHEY_SIMPLEX,0.55,(0,220,120),2,cv2.LINE_AA)
    cv2.imwrite(str(OUT/'result.png'),image)

def tracking_worker():
    try:
        while not track_stop.wait(track_state['interval_s']):
            sample=camera.latest
            if sample is None or time.time()-sample[0]>5: continue
            if not lock.acquire(False):
                track_state['skipped']+=1
                continue
            state['busy']=True
            try:
                result=infer_frame(track_state['query'],sample,OUT/'track_raw')
                detections=result.get('detections',[])
                confirmed=confirmed_tracking_detections(detections)
                track_history.append(detections)
                del track_history[:-3]
                result['detections']=confirmed
                result['tracking_confirmed']=bool(confirmed)
                if confirmed:
                    # Keep the last confirmed frame visible; an isolated
                    # missed frame must not erase a valid target on the UI.
                    render_tracking_result(confirmed)
                    state['result']=result
                    track_state['last_detections']=len(confirmed)
                elif state.get('result') is None or not state['result'].get('tracking_confirmed'):
                    render_tracking_result([])
                state['error']=None
                track_state['frames']+=1
                if confirmed: track_state['recognized']+=1
            except Exception as exc:
                track_state['error']=str(exc); state['error']=str(exc)
            finally:
                state['busy']=False
                lock.release()
    finally:
        with track_guard: track_state['running']=False

def start_tracking(query):
    query=query.strip()
    if not query or len(query)>200 or any(ord(c)<32 for c in query): raise ValueError('请输入有效物体名称或描述')
    with track_guard:
        if track_state['running']: raise ValueError('连续识别已经在运行')
        track_stop.clear()
        track_history.clear()
        state['result']=None
        track_state.update(running=True,query=query,frames=0,recognized=0,skipped=0,last_detections=0,error=None,started_at=time.time())
        threading.Thread(target=tracking_worker,daemon=True).start()
    return dict(track_state)

def stop_tracking():
    track_stop.set()
    track_history.clear()
    return {'ok':True}
class Handler(BaseHTTPRequestHandler):
    def reply(self,body,mime='application/json',code=200):
        self.send_response(code); self.send_header('Content-Type',mime); self.send_header('Content-Length',str(len(body))); self.send_header('Cache-Control','no-store'); self.end_headers()
        try:self.wfile.write(body)
        except (BrokenPipeError,ConnectionResetError):pass
    def do_GET(self):
        path=urlparse(self.path).path
        if path=='/api/people/camera':
            if self.client_address[0] not in ('127.0.0.1','::1'):
                return self.reply(b'{"error":"loopback only"}',code=403)
            try:
                from people_camera import camera_packet
                include_zoom = parse_qs(urlparse(self.path).query).get('zoom', ['1'])[0] != '0'
                return self.reply(camera_packet(camera, include_zoom=include_zoom),'application/x-npz')
            except Exception as exc:
                return self.reply(json.dumps({'error':str(exc)},ensure_ascii=False).encode(),code=503)
        if path=='/api/stereo/pair':
            if self.client_address[0] not in ('127.0.0.1','::1'):
                return self.reply(b'{"error":"loopback only"}',code=403)
            if not isinstance(camera, StereoCamera):
                return self.reply(b'{"error":"stereo camera inactive"}',code=409)
            with camera.latest_lock:
                pair=camera.latest_pair
            if pair is None or time.monotonic()-pair[0]>.5:
                return self.reply(b'{"error":"stereo pair stale"}',code=503)
            import io, numpy as np
            left_ok,left=cv2.imencode('.jpg',pair[1],[cv2.IMWRITE_JPEG_QUALITY,90])
            right_ok,right=cv2.imencode('.jpg',pair[2],[cv2.IMWRITE_JPEG_QUALITY,90])
            if not left_ok or not right_ok:return self.send_error(503)
            payload=io.BytesIO()
            np.savez_compressed(payload,monotonic_stamp=np.float64(pair[0]),left_jpeg=left,right_jpeg=right)
            return self.reply(payload.getvalue(),'application/x-npz')
        if path=='/semantic/status':return self.reply(json.dumps(semantic.status(),ensure_ascii=False).encode())
        if path=='/semantic/search':
            params=parse_qs(urlparse(self.path).query)
            query=params.get('query',[''])[0]
            if len(query)>100:return self.send_error(400)
            return self.reply(json.dumps({'objects':semantic.store.search(query,map_id=params.get('map_id',[None])[0])},ensure_ascii=False).encode())
        if path=='/semantic/frame.jpg':
            if semantic.latest_image:return self.reply(semantic.latest_image,'image/jpeg')
            return self.send_error(404)
        if path.startswith('/semantic/file/'):
            try:return self.reply(semantic.asset(path.removeprefix('/semantic/file/')).read_bytes(),'image/jpeg')
            except (ValueError,OSError):return self.send_error(404)
        if path in ('/memory','/semantic'):return self.reply((ROOT/'semantic.html').read_bytes(),'text/html; charset=utf-8')
        if path=='/memory/legacy':return self.reply((ROOT/'memory.html').read_bytes(),'text/html; charset=utf-8')
        if path=='/memory/status':return self.reply(json.dumps(memory.state,ensure_ascii=False).encode())
        if path=='/memory/search':return self.reply(json.dumps({'observations':memory.search(parse_qs(urlparse(self.path).query).get('query',[''])[0])},ensure_ascii=False).encode())
        if path.startswith('/memory/file/'):
            try:return self.reply(memory.asset(path[len('/memory/file/'):]).read_bytes(),'image/jpeg')
            except (ValueError,OSError):return self.send_error(404)
        if path=='/patrol/status':return self.reply(json.dumps(dict(recording=patrol.record,job=patrol.job,sessions=patrol.sessions()),ensure_ascii=False).encode())
        if path=='/track/status':return self.reply(json.dumps(dict(track_state),ensure_ascii=False).encode())
        if path=='/patrol/searches':
            try:return self.reply(json.dumps(patrol.searches(parse_qs(urlparse(self.path).query).get('session',[''])[0]),ensure_ascii=False).encode())
            except ValueError:return self.send_error(400)
        if path.startswith('/patrol/file/'):
            try:
                asset,mime=patrol.asset(path.removeprefix('/patrol/file/').split('/'))
                with asset.open('rb') as stream:
                    self.send_response(200);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(asset.stat().st_size));self.end_headers()
                    import shutil
                    shutil.copyfileobj(stream,self.wfile,1024*1024)
            except (ValueError,FileNotFoundError):self.send_error(404)
            except (BrokenPipeError,ConnectionResetError):pass
            return
        if path in ('/','/view'):return self.reply((ROOT/'live.html').read_bytes(),'text/html; charset=utf-8')
        if path=='/health':
            yoloe_active = yoloe_loaded()
            depth_engine=getattr(camera,'depth_engine',None)
            return self.reply(json.dumps(dict(state,tracking=dict(track_state),model_loaded=runtime.loaded() or yoloe_active, model_backend='yolo26m_objv1_seg_person_bpu' if yoloe_active else ('nanoowl' if runtime.loaded() else None), camera_online=camera.latest is not None and time.time()-camera.latest[0]<5, camera_error=camera.error, camera_source=camera_source, metric_depth_available=getattr(camera, 'has_metric_depth', True), people_full_fov=getattr(camera,'full_fov_people',False), stereo_depth_error=getattr(camera,'depth_error',None), stereo_depth_valid_fraction=getattr(depth_engine,'last_valid_fraction',None), people_depth_valid_fraction=getattr(depth_engine,'last_raw_valid_fraction',None), stereo_depth_processing_s=getattr(depth_engine,'last_processing_s',None)),ensure_ascii=False).encode())
        if path=='/preview.jpg':
            with camera.latest_lock:
                sample=camera.latest
            if sample is None or time.monotonic()-sample[1]>.8:return self.send_error(503)
            ok,jpeg=cv2.imencode('.jpg',sample[2],[cv2.IMWRITE_JPEG_QUALITY,75])
            if not ok:return self.send_error(503)
            return self.reply(jpeg.tobytes(),'image/jpeg')
        if path=='/snapshot.jpg' and camera.latest is not None:
            ok,image=cv2.imencode('.jpg',camera.latest[2]);return self.reply(image.tobytes(),'image/jpeg')
        if path=='/snapshot-hd.jpg':
            _, high = camera.people_snapshot()
            if high is None:return self.send_error(404)
            ok,image=cv2.imencode('.jpg',high[1],[cv2.IMWRITE_JPEG_QUALITY,90])
            if not ok:return self.send_error(503)
            return self.reply(image.tobytes(),'image/jpeg')
        if path=='/result.png' and state['result'] and not state['busy']:return self.reply((OUT/'result.png').read_bytes(),'image/png')
        self.send_error(404)
    def do_POST(self):
        if self.path in ('/semantic/start','/semantic/stop'):
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<=length<=2048:raise ValueError('请求长度无效')
                data=json.loads(self.rfile.read(length) or '{}')
                if not isinstance(data,dict):raise ValueError('请求格式无效')
                if self.path=='/semantic/start':
                    if track_state['running'] or patrol.record or (patrol.job or {}).get('status')=='searching':
                        raise ValueError('请先停止当前连续识别、录像或录像搜索')
                    result=semantic.start(data)
                else:result=semantic.stop(data)
                return self.reply(json.dumps(result,ensure_ascii=False).encode())
            except Exception as exc:return self.reply(json.dumps({'error':str(exc)},ensure_ascii=False).encode(),code=400)
        if semantic.status()['running'] and self.path in ('/model/unload','/memory/observe','/track/start','/locate','/patrol/search'):
            return self.reply(json.dumps({'error':'实时物体记忆正在使用视觉服务，请先停止实时记忆'},ensure_ascii=False).encode(),code=409)
        if self.path=='/memory/observe':
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=2048:raise ValueError('请求长度无效')
                data=json.loads(self.rfile.read(length))
                return self.reply(json.dumps(memory.observe(data.get('query')),ensure_ascii=False).encode(),code=202)
            except Exception as exc:return self.reply(json.dumps({'error':str(exc)},ensure_ascii=False).encode(),code=400)
        if self.path=='/model/unload':
            if not lock.acquire(False):return self.reply(b'{"error":"model busy"}',code=409)
            try:
                runtime.unload(); yoloe_unload(); return self.reply(b'{"ok":true}')
            finally:lock.release()
        if self.path=='/track/start':
            try:
                length=int(self.headers.get('Content-Length','0'))
                if length<1 or length>2048:raise ValueError('请求长度无效')
                data=json.loads(self.rfile.read(length))
                return self.reply(json.dumps(start_tracking(data.get('query','')),ensure_ascii=False).encode(),code=202)
            except (ValueError,OSError) as exc:return self.reply(json.dumps({'error':str(exc)},ensure_ascii=False).encode(),code=400)
        if self.path=='/track/stop':
            return self.reply(json.dumps(stop_tracking(),ensure_ascii=False).encode())
        if self.path.startswith('/patrol/'):
            try:
                length=int(self.headers.get('Content-Length','0'))
                if length<0 or length>2048:raise ValueError('请求过长')
                data=json.loads(self.rfile.read(length) or '{}')
                if self.path=='/patrol/start':result=patrol.start()
                elif self.path=='/patrol/stop':patrol.stop();result={'ok':True}
                elif self.path=='/patrol/cancel':patrol.cancel.set();result={'ok':True}
                elif self.path=='/patrol/search':
                    query=data.get('query','').strip()
                    if not query or len(query)>200 or any(ord(c)<32 for c in query):raise ValueError('请输入有效物体名称')
                    if not state['ready']:raise ValueError('模型未就绪')
                    result=patrol.search(data.get('session'),query)
                else:return self.send_error(404)
                return self.reply(json.dumps(result,ensure_ascii=False).encode())
            except (ValueError,OSError) as e:return self.reply(json.dumps({'error':str(e)},ensure_ascii=False).encode(),code=400)
        if self.path!='/locate':return self.send_error(404)
        length=int(self.headers.get('Content-Length','0'))
        if length<1 or length>2048:return self.send_error(400)
        try:
            query=json.loads(self.rfile.read(length)).get('query','').strip()
            if not query or len(query)>200 or any(ord(c)<32 for c in query):raise ValueError()
        except Exception:return self.send_error(400)
        sample=camera.latest
        if not state['ready'] or sample is None or time.time()-sample[0]>5:return self.reply(b'{"error":"not ready"}',code=503)
        if not lock.acquire(False):return self.reply(b'{"error":"busy"}',code=409)
        state['busy']=True
        threading.Thread(target=infer,args=(query,sample),daemon=True).start()
        self.reply(b'{"accepted":true}',code=202)
    def log_message(self,*args):pass
try:ThreadingHTTPServer(('0.0.0.0',8091),Handler).serve_forever()
finally:semantic.stop();runtime.unload();camera.close()
