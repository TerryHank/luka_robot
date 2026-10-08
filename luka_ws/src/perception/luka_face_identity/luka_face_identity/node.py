"""Face enrollment/recognition beside official MOT; never a motion authority."""
import json
from pathlib import Path
import threading
import time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image
from ai_msgs.msg import PerceptionTargets

from .identity import IdentityStore,IdentityRecognizer,EnrollmentManager
from .vision import FaceFeatures


class FaceIdentity(Node):
    def __init__(self):
        super().__init__('luka_face_identity')
        self.declare_parameter('enable_face',False)
        self.declare_parameter('database_path','/home/sunrise/luka_data/recordings/person_follow/people.sqlite3')
        self.declare_parameter('model_directory','/home/sunrise/luka_data/ml_models/person_follow')
        self.declare_parameter('http_port',8098)
        self.store=IdentityStore(Path(self.get_parameter('database_path').value))
        self.recognizer=IdentityRecognizer(self.store)
        self.enrollment=EnrollmentManager(self.store,target=12,min_interval_s=1.0)
        self.lock=threading.RLock()
        self.features=None
        self.enabled=False
        self.last_image=None
        self.targets=None
        self.tracks=[]
        self.selected_id=None
        self.jpeg=None
        self.last_inference=0.0
        self.frame_width=640
        self.frame_height=480
        self.frame_no=0
        self.error=None
        self.create_subscription(Image,'/camera/color/image_raw',self.image,qos_profile_sensor_data)
        self.create_subscription(PerceptionTargets,'/tros_mot_targets',self.mot,qos_profile_sensor_data)
        self.create_timer(.2,self.expire)
        self.server=ThreadingHTTPServer(('127.0.0.1',self.get_parameter('http_port').value),handler(self))
        self.compat_server=ThreadingHTTPServer(('127.0.0.1',8097),handler(self))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        threading.Thread(target=self.compat_server.serve_forever,daemon=True).start()
        if self.get_parameter('enable_face').value:self.start_face()

    def age(self,stamp):
        return self.get_clock().now().nanoseconds*1e-9-stamp.sec-stamp.nanosec*1e-9

    def start_face(self):
        with self.lock:
            if self.features is None:
                models=Path(self.get_parameter('model_directory').value)
                self.features=FaceFeatures(models/'yunet.onnx',models/'sface.onnx')
            self.enabled=True
        return self.status()

    def mot(self,message):
        with self.lock:self.targets=message

    def expire(self):
        with self.lock:
            if (self.targets is None or not -.05<=self.age(self.targets.header.stamp)<=.6 or
                self.last_image is None or not -.05<=self.age(self.last_image)<=.6):
                self.tracks=[]
                self.selected_id=None
                self.recognizer.prune([])
                self.enrollment.on_tracks([])

    def image(self,message):
        with self.lock:
            self.last_image=message.header.stamp
            self.frame_width,self.frame_height=message.width,message.height
            self.frame_no+=1
            if not self.enabled or time.monotonic()-self.last_inference<.4:return
            self.last_inference=time.monotonic()
            targets=self.targets
            if (targets is None or not -.05<=self.age(message.header.stamp)<=.6 or
                abs((targets.header.stamp.sec-message.header.stamp.sec)+
                    (targets.header.stamp.nanosec-message.header.stamp.nanosec)*1e-9)>.10 or
                targets.header.frame_id!=message.header.frame_id):
                self.tracks=[];self.recognizer.prune([]);self.enrollment.on_tracks([])
                self.error='等待新鲜且对齐的官方MOT与相机数据';return
            if message.encoding not in ('rgb8','bgr8') or message.step<message.width*3:
                self.error='不支持的相机图像格式';return
            if len(message.data)!=message.height*message.step:
                self.error='图像长度错误';return
            image=np.frombuffer(bytes(message.data),np.uint8).reshape(message.height,message.step)
            image=image[:,:message.width*3].reshape(message.height,message.width,3).copy()
            if message.encoding=='rgb8':image=cv2.cvtColor(image,cv2.COLOR_RGB2BGR)
            ok,encoded=cv2.imencode('.jpg',image)
            self.jpeg=encoded.tobytes() if ok else None
            rows=[]
            for target in targets.targets:
                roi=next((r for r in target.rois if r.type=='person'),None)
                if target.type!='person' or roi is None or not roi.rect.width or not roi.rect.height:continue
                box=[roi.rect.x_offset,roi.rect.y_offset,roi.rect.x_offset+roi.rect.width,
                     roi.rect.y_offset+roi.rect.height]
                result=self.features.face_features(image,box)
                identity={'known':False,'reason':result['reason']}
                if result['accepted']:
                    identity=self.recognizer.observe(target.track_id,result['embedding'])
                    self.enrollment.add_sample(target.track_id,result['embedding'],
                        quality_ok=result.get('enrollment_eligible',False))
                else:self.recognizer.forget(target.track_id)
                identity.update(state='matched' if identity.get('known') else 'unknown',
                                id=identity.get('profile_id'))
                profile=next((p for p in self.store.list_profiles() if p['id']==identity.get('id')),None)
                if profile:
                    identity.update({k:v for k,v in profile.items() if k.startswith('voice_')})
                rows.append({'track_id':target.track_id,'bbox':box,'visible':True,
                             'identity':identity,'face_reason':result['reason'],
                             'observation_strength':'strong_detection','association_ambiguous':False})
            ids=[r['track_id'] for r in rows]
            self.recognizer.prune(ids);self.enrollment.on_tracks(ids)
            self.tracks=rows;self.error=None
            if self.selected_id not in ids:self.selected_id=None

    def status(self):
        with self.lock:
            return {'active':self.enabled,'mode':'face_identity','motion_enabled':False,
                    'tracks':self.tracks,'profiles':self.store.list_profiles(),
                    'selected_track_id':self.selected_id,'frame_width':self.frame_width,'frame_height':self.frame_height,
                    'frame_at':None if self.last_image is None else self.last_image.sec+self.last_image.nanosec*1e-9,
                    'frame_no':self.frame_no,'metric_depth_available':False,
                    'camera_age':None if self.last_image is None else self.age(self.last_image),
                    'enrollment':self.enrollment.status(),'error':self.error,
                    'target_session':{'active':False,'reason':'identity_is_not_motion_authority'}}

    def command(self,name,data):
        with self.lock:
            if name=='start':return self.start_face()
            if name=='stop':
                self.enabled=False;self.tracks=[];self.enrollment.cancel();return self.status()
            if name=='delete-profile':
                if not self.store.delete_profile(str(data.get('id',''))):raise ValueError('档案不存在')
            elif name=='select':
                ident=int(data.get('track_id',-1))
                if ident not in [r['track_id'] for r in self.tracks]:raise ValueError('当前MOT编号不可见')
                self.selected_id=ident
            elif name=='unlock':self.selected_id=None;self.enrollment.cancel()
            elif name in ('enroll','enroll-start','supplement'):
                ident=data.get('track_id')
                if not self.enabled or ident not in [r['track_id'] for r in self.tracks]:
                    raise ValueError('需要当前可见的官方MOT人体编号')
                self.enrollment.start(data.get('name',''),ident,profile_id=data.get('profile_id'))
            elif name in ('enroll-finish','finish-enrollment'):self.enrollment.finish()
            elif name in ('enroll-cancel','cancel-enrollment'):self.enrollment.cancel()
            elif name=='bind-voice':self.store.bind_voice_profile(data.get('id'),data.get('voice_profile_id'))
            elif name=='unlink-voice':self.store.unlink_voice_profile(data.get('id'))
            else:raise ValueError('旧指定跟随/自定义跟踪接口已退役；本服务只提供人脸数据')
            return self.status()

    def close(self):
        self.server.shutdown();self.server.server_close()
        self.compat_server.shutdown();self.compat_server.server_close();self.store.close()


def handler(owner):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def reply(self,value,status=200):
            encoded=json.dumps(value,ensure_ascii=False).encode()
            self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Content-Length',str(len(encoded)));self.end_headers();self.wfile.write(encoded)
        def do_GET(self):
            if self.path.split('?',1)[0] in ('/api/people/status','/api/people/follow-state'):
                return self.reply(owner.status())
            if self.path.split('?',1)[0]=='/api/people/frame.jpg':
                if owner.jpeg is None:return self.reply({'error':'camera unavailable'},503)
                self.send_response(200);self.send_header('Content-Type','image/jpeg')
                self.send_header('Content-Length',str(len(owner.jpeg)));self.end_headers();self.wfile.write(owner.jpeg);return
            self.reply({'error':'not found'},404)
        def do_POST(self):
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<=size<=4096:raise ValueError('请求过大')
                data=json.loads(self.rfile.read(size) or b'{}')
                if not isinstance(data,dict):raise ValueError('请求格式错误')
                from urllib.parse import urlparse
                origin=self.headers.get('Origin')
                if origin and urlparse(origin).netloc!=self.headers.get('Host'):
                    raise ValueError('请从本机监控页面操作')
                prefix='/api/people/'
                if not self.path.startswith(prefix):return self.reply({'error':'not found'},404)
                self.reply(dict(ok=True,**owner.command(self.path[len(prefix):],data)))
            except (ValueError,KeyError) as error:self.reply({'error':str(error)},409)
    return Handler


def main():
    rclpy.init();node=FaceIdentity()
    try:rclpy.spin(node)
    except KeyboardInterrupt:pass
    finally:
        node.close();node.destroy_node();rclpy.try_shutdown()
