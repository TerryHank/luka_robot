"""Persistent RGB-D observations. No movement commands are issued here."""
import json,math,sqlite3,time,uuid,threading,urllib.request,shutil
from pathlib import Path
import cv2
import numpy as np

def transform_point(point,transform):
    q=np.array(transform['quaternion_xyzw'],dtype=float)
    t=np.array(transform['translation'],dtype=float)
    if q.shape!=(4,) or t.shape!=(3,) or not np.isfinite(q).all() or not np.isfinite(t).all() or abs(np.linalg.norm(q)-1)>.01:
        raise ValueError('invalid rigid transform')
    q=q/np.linalg.norm(q);v=q[:3];p=np.array(point,dtype=float)
    return (p+2*np.cross(v,np.cross(v,p)+q[3]*p)+t).tolist()

def map_position(point,context,extrinsic):
    if point is None:return None,'invalid_depth'
    if not extrinsic or not (extrinsic.get('verified') is True or extrinsic.get('source')=='user_measurement'):
        return None,'camera_extrinsic_unverified'
    if not context.get('map_from_base'):return None,'map_pose_unavailable'
    base=transform_point(point,extrinsic['base_from_camera_optical'])
    return transform_point(base,context['map_from_base']),('estimated_manual_extrinsic' if extrinsic.get('source')=='user_measurement' else 'estimated_candidate')

class ObjectMemory:
    def __init__(self,root,camera,model_lock,locate,position):
        self.root=(Path('/home/sunrise/luka_data/recordings/locateanything_trial_20260907/object_memory') if Path(root).resolve()==Path(__file__).resolve().parent else Path(root)/'object_memory');self.root.mkdir(exist_ok=True)
        self.db=self.root/'observations.sqlite3'
        self.camera=camera;self.lock=model_lock;self.locate=locate;self.position=position
        self.state={'busy':False,'result':None,'error':None}
        with self.connect() as db:db.execute('CREATE TABLE IF NOT EXISTS observations (id TEXT PRIMARY KEY, captured_at REAL NOT NULL, query TEXT NOT NULL, payload TEXT NOT NULL)')

    def connect(self):return sqlite3.connect(str(self.db),timeout=10)

    def search(self,query=''):
        with self.connect() as db:
            rows=db.execute('SELECT payload FROM observations WHERE instr(query,?)>0 ORDER BY captured_at DESC LIMIT 50',(query,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def observe(self,query):
        if not isinstance(query,str) or not query.strip() or len(query)>100:raise ValueError('请输入 1–100 字的物体名称')
        query=query.strip()
        if any(ord(c)<32 for c in query):raise ValueError('物体名称不能包含换行或控制字符')
        if shutil.disk_usage(self.root).free<512*1024*1024:raise ValueError('可用磁盘空间不足 512 MB')
        if not self.lock.acquire(False):raise ValueError('模型正在处理其他任务')
        try:
            sample=self.camera.latest
            if sample is None or time.time()-sample[0]>.5:raise ValueError('相机画面不新鲜')
            if sample[4]>.1:raise ValueError('彩色与深度配对延迟过大，请重试')
            with urllib.request.urlopen('http://127.0.0.1:8503/api/object/pose?stamp='+str(sample[0]),timeout=2) as response:context=json.load(response)
            if not context.get('stationary') or context.get('navigation_active'):
                raise ValueError('请先停止导航并松开手柄，停稳后再观察')
            sample=(sample[0],sample[1],sample[2].copy(),sample[3].copy(),sample[4])
            self.state={'busy':True,'result':None,'error':None}
            threading.Thread(target=self.run,args=(query,sample,context),daemon=True).start()
            return {'accepted':True}
        except Exception:
            self.lock.release();raise

    def run(self,query,sample,context):
        observation_id=uuid.uuid4().hex
        directory=self.root/observation_id;directory.mkdir()
        try:
            rgb,depth=sample[2:4];h,w=rgb.shape[:2]
            resized=cv2.resize(rgb,(round(w*448/max(h,w)),round(h*448/max(h,w))))
            if not cv2.imwrite(str(directory/'rgb.jpg'),rgb):raise OSError('保存图片失败')
            if not cv2.imwrite(str(directory/'depth.png'),depth):raise OSError('保存深度失败')
            cv2.imwrite(str(directory/'input.jpg'),resized)
            payload={'id':observation_id,'query':query,'captured_at':sample[0],
                'rgb_url':f'/memory/file/{observation_id}/rgb.jpg',
                'image_url':f'/memory/file/{observation_id}/marked.jpg',
                'context':context,'pairing':'approximate_host_pairing','pair_skew_s':sample[4],
                'calibration':self.camera.calibration,'detections':[], 'status':'captured'}
            (directory/'capture.json').write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8')
            result=self.locate(directory/'input.jpg',query,directory/'result')
            extrinsic_path=self.root/'camera_extrinsic.json'
            extrinsic=json.loads(extrinsic_path.read_text()) if extrinsic_path.exists() else None
            payload['camera_extrinsic']=extrinsic
            marked=rgb.copy()
            for detection in result.get('detections',[]):
                box=detection.get('box',[])
                if len(box)!=4 or not all(math.isfinite(float(v)) for v in box):continue
                box=[float(box[0])*w/resized.shape[1],float(box[1])*h/resized.shape[0],float(box[2])*w/resized.shape[1],float(box[3])*h/resized.shape[0]]
                box=[max(0,min(w-1,box[0])),max(0,min(h-1,box[1])),max(0,min(w-1,box[2])),max(0,min(h-1,box[3]))]
                if box[2]<=box[0] or box[3]<=box[1]:continue
                point,quality=self.position(depth,box,self.camera.calibration['color'],self.camera.calibration['color_dist'])
                mapped,reason=map_position(point,context,extrinsic)
                item={'label':detection.get('label',query),'box_rgb':box,'camera_xyz_m':point,
                    'map_xyz_m':mapped,'map_status':reason,'depth_quality':quality,'confirmed':False}
                payload['detections'].append(item)
                cv2.rectangle(marked,(int(box[0]),int(box[1])),(int(box[2]),int(box[3])),(0,200,255),2)
            payload['status']='candidates' if payload['detections'] else 'not_detected'
            payload['completed_at']=time.time();payload['inference_seconds']=result.get('inference_seconds')
            cv2.imwrite(str(directory/'marked.jpg'),marked)
            (directory/'observation.json').write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8')
            with self.connect() as db:db.execute('INSERT INTO observations VALUES (?,?,?,?)',(observation_id,sample[0],query,json.dumps(payload,ensure_ascii=False)))
            self.state['result']=payload
        except Exception as exc:self.state['error']=str(exc)
        finally:self.state['busy']=False;self.lock.release()

    def asset(self,path):
        parts=path.split('/')
        if len(parts)!=2 or len(parts[0])!=32 or any(c not in '0123456789abcdef' for c in parts[0]) or parts[1] not in ('rgb.jpg','marked.jpg'):
            raise ValueError('invalid asset')
        return self.root/parts[0]/parts[1]
