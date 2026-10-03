#!/usr/bin/env python3
"""On-device object-location memory and read-only LAN query API."""
import argparse
import fcntl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import pathlib
import signal
import threading
import time
from urllib.parse import parse_qs, urlparse
import cv2
from camera import Camera, object_position
from detector import Detector
from memory import Memory, CHINESE

ROOT = pathlib.Path(__file__).resolve().parent
DESKTOP_CLASSES = set('backpack,umbrella,handbag,suitcase,bottle,wine glass,cup,fork,knife,spoon,bowl,banana,apple,sandwich,orange,broccoli,carrot,hot dog,pizza,donut,cake,chair,couch,potted plant,bed,dining table,tv,laptop,mouse,remote,keyboard,cell phone,microwave,oven,toaster,sink,refrigerator,book,clock,vase,scissors,teddy bear,hair drier,toothbrush'.split(','))


def atomic_bytes(path, content):
    temp = path.with_suffix(path.suffix+'.tmp')
    temp.write_bytes(content)
    temp.replace(path)


def serve(args):
    data = ROOT/'data'
    data.mkdir(exist_ok=True)
    pictures = data/'objects'
    pictures.mkdir(exist_ok=True)
    lock = (data/'capture.lock').open('w')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    memory = Memory(data/'memory.sqlite3')
    detector = Detector(ROOT,args.confidence,args.backend)
    camera = Camera(ROOT/'sdk',args.camera)
    atomic_bytes(data/'calibration.json',json.dumps(camera.calibration,indent=2).encode())
    stop = threading.Event()
    status = {'state':'starting','frame':args.frame,'backend':detector.backend,
              'started_at':time.time(),'processed_frames':0,'last_frame_at':None,
              'coordinate_axes':'x=right,y=down,z=forward; metres; fixed RGB camera',
              'registration':'Orbbec OpenNI native depth-to-color, factory calibration',
              'pairing':'approximate host pairing, static-scene use',
              'classes':{k:v for k,v in CHINESE.items() if args.all_classes or k in DESKTOP_CLASSES},'last_error':None}

    def health():
        result = dict(status)
        result['ok'] = result['state']=='running' and result['last_frame_at'] is not None and time.time()-result['last_frame_at']<5
        return result

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            target = urlparse(self.path)
            query = parse_qs(target.query)
            if target.path in ('/','/health'):
                result = health()
                self.reply(json.dumps(result,ensure_ascii=False,indent=2).encode(),'application/json; charset=utf-8',200 if result['ok'] else 503)
            elif target.path=='/view':
                self.reply((ROOT/'viewer.html').read_bytes(),'text/html; charset=utf-8')
            elif target.path=='/search':
                selected_frame = query.get('frame',[args.frame])[0]
                result = memory.search(query.get('q',[''])[0],selected_frame)
                result['camera_online'] = health()['ok']
                result['note'] = '仅按物体类别查询；暂不理解颜色、所属人或自由描述。'
                for item in result['objects']:
                    item['currently_visible'] = item['recently_seen'] and result['camera_online'] and item['frame']==args.frame
                self.reply(json.dumps(result,ensure_ascii=False,indent=2).encode(),'application/json; charset=utf-8')
            elif target.path=='/snapshot.jpg':
                self.picture(data/'latest.jpg')
            elif target.path.startswith('/objects/'):
                name = target.path.removeprefix('/objects/')
                if len(name)==20 and name.endswith('.jpg') and all(c in '0123456789abcdef' for c in name[:-4]):
                    self.picture(pictures/name)
                else:
                    self.send_error(404)
            else:
                self.send_error(404)

        def picture(self,path):
            try:
                self.reply(path.read_bytes(),'image/jpeg')
            except FileNotFoundError:
                self.send_error(404)

        def reply(self,body,mime,code=200):
            self.send_response(code)
            self.send_header('Content-Type',mime)
            self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store')
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError,ConnectionResetError):
                pass

        def log_message(self,*args):
            pass

    server = ThreadingHTTPServer((args.bind,args.port),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    for sig in (signal.SIGTERM,signal.SIGINT):
        signal.signal(sig,lambda *_:stop.set())
    last_processed = 0
    last_cleanup = 0
    snapshot_times = {}
    print(json.dumps({'event':'started','backend':detector.backend,'bind':args.bind,'port':args.port,'frame':args.frame}),flush=True)
    try:
        while not stop.is_set():
            if camera.error:
                raise RuntimeError(camera.error)
            sample = camera.latest
            if sample is None:
                if time.time()-status['started_at']>10:
                    raise RuntimeError('Camera did not deliver a frame')
                stop.wait(.1)
                continue
            ts,mono,rgb,depth,skew = sample
            if time.monotonic()-mono>3:
                raise RuntimeError('Camera stopped delivering fresh frames')
            if mono==last_processed:
                stop.wait(.03)
                continue
            last_processed = mono
            begin = time.monotonic()
            detections = detector.detect(rgb)
            if not args.all_classes:
                detections = [d for d in detections if d['class'] in DESKTOP_CLASSES]
            for detection in detections:
                if skew<=.1:
                    xyz,quality = object_position(depth,detection['bbox'],camera.calibration['color'],camera.calibration['color_dist'])
                else:
                    xyz,quality = None,{'reason':'rgb_depth_host_pairing_too_slow'}
                detection['xyz_m'] = xyz
                detection['depth_quality'] = quality
            observations = memory.update(detections,args.frame,ts)
            annotated = rgb.copy()
            for item in observations:
                x1,y1,x2,y2 = item['bbox']
                color = (80,230,100) if item['hits']>=3 else (0,190,255)
                cv2.rectangle(annotated,(x1,y1),(x2,y2),color,2)
                label = f"{item['class']} {item['confidence']:.2f}"
                if item['xyz_m']:
                    label+=f" z={item['xyz_m'][2]:.2f}m"
                cv2.putText(annotated,label,(x1,max(18,y1-6)),cv2.FONT_HERSHEY_SIMPLEX,.5,color,1,cv2.LINE_AA)
                oid = item['id']
                if item['hits']>=3 and ts-snapshot_times.get(oid,0)>=10:
                    ok,jpg = cv2.imencode('.jpg',rgb[y1:y2,x1:x2],[cv2.IMWRITE_JPEG_QUALITY,85])
                    if ok:
                        atomic_bytes(pictures/f'{oid}.jpg',jpg.tobytes())
                        snapshot_times[oid]=ts
            cv2.putText(annotated,time.strftime('%Y-%m-%d %H:%M:%S',time.localtime(ts)),(10,470),cv2.FONT_HERSHEY_SIMPLEX,.5,(0,255,255),1)
            ok,jpg = cv2.imencode('.jpg',annotated,[cv2.IMWRITE_JPEG_QUALITY,85])
            if ok:
                atomic_bytes(data/'latest.jpg',jpg.tobytes())
            status.update(state='running',last_frame_at=ts,processed_frames=status['processed_frames']+1,
                          inference_and_memory_ms=round((time.monotonic()-begin)*1000,1),
                          detections=len(detections),confirmed_visible=sum(o['hits']>=3 for o in observations),
                          depth_valid_fraction=round(float((depth>0).mean()),3),host_pairing_ms=round(skew*1000,1))
            atomic_bytes(data/'status.json',json.dumps(status,ensure_ascii=False,indent=2).encode())
            if ts-last_cleanup>=3600:
                memory.cleanup(ts)
                last_cleanup=ts
            if status['processed_frames']%60==0:
                print(json.dumps({k:status[k] for k in ('processed_frames','backend','detections','confirmed_visible','inference_and_memory_ms')}),flush=True)
            stop.wait(max(0,args.interval-(time.monotonic()-begin)))
    except Exception as exc:
        status.update(state='error',last_error=repr(exc))
        raise
    finally:
        if status['state']!='error':
            status['state']='stopped'
        atomic_bytes(data/'status.json',json.dumps(status,ensure_ascii=False,indent=2).encode())
        server.shutdown()
        camera.close()


def main():
    parser = argparse.ArgumentParser(description='固定相机物体空间记忆')
    commands = parser.add_subparsers(dest='command',required=True)
    live = commands.add_parser('serve')
    live.add_argument('--bind',default='192.168.3.251')
    live.add_argument('--port',type=int,default=8091)
    live.add_argument('--camera',type=int,default=0)
    live.add_argument('--frame',default='desktop-camera-v1')
    live.add_argument('--backend',choices=['auto','gpu','cpu'],default='gpu')
    live.add_argument('--confidence',type=float,default=.4)
    live.add_argument('--all-classes',action='store_true',help='记忆全部 COCO 类别，默认仅记忆桌面/室内物体')
    live.add_argument('--interval',type=float,default=.5)
    query = commands.add_parser('query')
    query.add_argument('text',nargs='?',default='')
    query.add_argument('--frame',default='desktop-camera-v1')
    query.add_argument('--json',action='store_true')
    commands.add_parser('status')
    args = parser.parse_args()
    if args.command=='serve':
        serve(args)
    elif args.command=='status':
        print((ROOT/'data/status.json').read_text())
    else:
        result = Memory(ROOT/'data/memory.sqlite3').search(args.text,args.frame)
        if args.json:
            print(json.dumps(result,ensure_ascii=False,indent=2))
        elif not result['count']:
            print('尚未记住匹配的物体。请确认物体属于支持类别，并在镜头前停留几秒。')
        else:
            for obj in result['objects']:
                xyz = obj.get('xyz_m')
                depth = f'前方 {xyz[2]:.2f} 米，左右偏移 {xyz[0]:+.2f} 米，上下偏移 {xyz[1]:+.2f} 米' if xyz else '无可靠深度，仅保存画面位置'
                print(f"{obj['label_zh']} [{obj['id']}]：画面{obj['image_location_zh']}，{depth}；最后看到 {obj['last_seen_local']}（{obj['age_seconds']} 秒前）")
            print(result['scope'])


if __name__=='__main__':
    main()
