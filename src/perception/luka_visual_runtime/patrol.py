from pathlib import Path
import json, pathlib, threading, time, uuid, shutil, re
import cv2
import urllib.request

def box_iou(a,b):
    ax1,ay1,ax2,ay2=a['box']; bx1,by1,bx2,by2=b['box']
    ix1,iy1=max(ax1,bx1),max(ay1,by1); ix2,iy2=min(ax2,bx2),min(ay2,by2)
    inter=max(0,ix2-ix1)*max(0,iy2-iy1)
    area_a=max(0,ax2-ax1)*max(0,ay2-ay1); area_b=max(0,bx2-bx1)*max(0,by2-by1)
    union=area_a+area_b-inter
    return inter/union if union else 0

def confirmed_detections(detections,recent):
    """Keep only detections repeated at a nearby place in a recent keyframe."""
    if not recent: return []
    confirmed=[]
    for detection in detections:
        if any(
            item['label']==detection['label'] and box_iou(item,detection)>=0.10
            for previous in recent[-2:] for item in previous
        ):
            confirmed.append(detection)
    return confirmed

def render_confirmed(source,prefix,detections):
    image=cv2.imread(str(source))
    if image is None: return
    for detection in detections:
        x1,y1,x2,y2=map(int,detection['box'])
        x1,y1=max(0,x1),max(0,y1); x2,y2=min(image.shape[1]-1,x2),min(image.shape[0]-1,y2)
        cv2.rectangle(image,(x1,y1),(x2,y2),(0,220,120),2)
        cv2.putText(image,f"{detection['label']} {detection['score']:.2f}",
                    (x1,max(20,y1-6)),cv2.FONT_HERSHEY_SIMPLEX,0.55,
                    (0,220,120),2,cv2.LINE_AA)
    cv2.imwrite(str(prefix.with_suffix('.png')),image)

def observation_context(stamp):
    try:
        with urllib.request.urlopen('http://127.0.0.1:8503/api/object/pose?stamp='+str(stamp),timeout=.65) as response:
            return json.load(response)
    except Exception as exc:
        return {'map_from_base':None,'map_pose_status':'unavailable','error':str(exc)[:120]}

def save(path, data):
    temp=path.with_suffix('.tmp'); temp.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8'); temp.replace(path)

class Patrol:
    def __init__(self, root, camera, model_lock, locate):
        self.root=Path('/home/sunrise/luka_data/recordings/locateanything_trial_20260907/patrols'); self.root.mkdir(exist_ok=True)
        self.camera=camera; self.model_lock=model_lock; self.locate=locate
        self.guard=threading.Lock(); self.record=None; self.job=None; self.cancel=threading.Event()
        for p in self.root.glob('*/session.json'):
            d=json.loads(p.read_text());
            if d['status']=='recording': d['status']='interrupted'; save(p,d)
        for p in self.root.glob('*/*/search.json'):
            d=json.loads(p.read_text())
            if d['status']=='searching':d['status']='failed';d['error']='服务重启中断了搜索，请重新搜索';save(p,d)
    def folder(self, ident):
        if not isinstance(ident,str) or not re.fullmatch('[0-9a-f]{32}',ident): raise ValueError('无效录像编号')
        p=self.root/ident
        if not (p/'session.json').exists(): raise ValueError('录像不存在')
        return p
    def sessions(self):
        return sorted([json.loads(p.read_text()) for p in self.root.glob('*/session.json')],key=lambda d:d['started_at'],reverse=True)
    def start(self):
        with self.guard:
            if self.record is not None: raise ValueError('正在录像')
            if not self.camera.latest or time.time()-self.camera.latest[0]>5: raise ValueError('相机未就绪')
            if shutil.disk_usage(self.root).free<2*1024**3: raise ValueError('剩余空间不足 2 GiB')
            ident=uuid.uuid4().hex; folder=self.root/ident; folder.mkdir()
            d=dict(id=ident,status='recording',started_at=time.time(),duration=0,frames=0,keyframes=0,fps=10,error=None)
            save(folder/'session.json',d); self.record=d; self.stop_event=threading.Event()
            self.thread=threading.Thread(target=self.capture,args=(folder,d,self.stop_event),daemon=True); self.thread.start()
            return d
    def capture(self,folder,d,stop):
        writer=None; index=[]; start=time.monotonic(); next_key=0
        try:
            writer=cv2.VideoWriter(str(folder/'video.avi'),cv2.VideoWriter_fourcc(*'MJPG'),10,(640,480))
            if not writer.isOpened(): raise RuntimeError('无法创建录像文件')
            with (folder/'frames.jsonl').open('a') as log:
                while not stop.is_set():
                    tick=time.monotonic(); sample=self.camera.latest
                    if not sample or time.time()-sample[0]>5: raise RuntimeError('相机断开，已结束录像')
                    elapsed=tick-start
                    if elapsed>=1800: break
                    if d['frames']%100==0 and shutil.disk_usage(folder).free<1024**3: raise RuntimeError('剩余空间不足 1 GiB，已结束录像')
                    writer.write(sample[2]); video_time=d['frames']/10; d['frames']+=1; d['duration']=elapsed
                    if elapsed>=next_key:
                        name=f'frame_{len(index):06d}.jpg'; image=cv2.resize(sample[2],(448,336))
                        if not cv2.imwrite(str(folder/name),image): raise RuntimeError('关键帧保存失败')
                        row=dict(file=name,seconds=elapsed,video_seconds=video_time,captured_at=sample[0],observation=observation_context(sample[0])); index.append(row)
                        log.write(json.dumps(row)+'\n'); log.flush(); d['keyframes']=len(index); save(folder/'session.json',d); next_key=elapsed+2
                    stop.wait(max(0,.1-(time.monotonic()-tick)))
        except Exception as e:d['error']=str(e)
        finally:
            if writer: writer.release()
            d['status']='complete' if not d['error'] else 'interrupted'; d['duration']=time.monotonic()-start
            save(folder/'session.json',d)
            with self.guard:self.record=None
    def stop(self):
        with self.guard:
            if self.record is None:raise ValueError('当前没有录像')
            self.stop_event.set(); thread=self.thread
        thread.join(5)
        if thread.is_alive():raise ValueError('录像正在收尾，请稍后重试')
    def search(self,ident,query):
        folder=self.folder(ident); session=json.loads((folder/'session.json').read_text())
        if session['status']=='recording':raise ValueError('请先停止录像再搜索')
        rows=[json.loads(line) for line in (folder/'frames.jsonl').read_text().splitlines()]
        if not rows:raise ValueError('录像没有可检索画面')
        if not self.model_lock.acquire(False):raise ValueError('模型正在识别，请稍后再试')
        jobid=uuid.uuid4().hex; dest=folder/jobid;dest.mkdir();self.cancel.clear()
        self.job=dict(id=jobid,session=ident,query=query,status='searching',done=0,total=len(rows),hits=[],error=None)
        threading.Thread(target=self.scan,args=(rows,folder,dest,self.job),daemon=True).start()
        return self.job
    def scan(self,rows,folder,dest,job):
        recent=[]
        try:
            for i,row in enumerate(rows):
                if self.cancel.is_set():job['status']='cancelled';break
                prefix=dest/f'hit_{i:06d}'
                result=self.locate(folder/row['file'],job['query'],prefix)
                raw_detections=result['detections']
                detections=confirmed_detections(raw_detections,recent)
                recent.append(raw_detections)
                del recent[:-3]
                if detections:
                    render_confirmed(folder/row['file'],prefix,detections)
                    job['hits'].append(dict(seconds=row['seconds'],video_seconds=row['video_seconds'],captured_at=row.get('captured_at'),observation=row.get('observation'),detections=detections,image=f'/patrol/file/{folder.name}/{dest.name}/{prefix.name}.png'))
                job['done']=i+1
                save(dest/'search.json',job)
            else:job['status']='complete'
        except Exception as e:job['status']='failed';job['error']=str(e)
        finally:save(dest/'search.json',job);self.model_lock.release()
    def searches(self,ident):
        folder=self.folder(ident)
        return [json.loads(p.read_text()) for p in sorted(folder.glob('*/search.json'),key=lambda p:p.stat().st_mtime)]
    def asset(self,parts):
        folder=self.folder(parts[0])
        if len(parts)==2 and parts[1]=='video.avi':return folder/'video.avi','video/x-msvideo'
        if len(parts)==3 and re.fullmatch('[0-9a-f]{32}',parts[1]) and re.fullmatch('hit_[0-9]{6}\.png',parts[2]):return folder/parts[1]/parts[2],'image/png'
        raise ValueError('文件不存在')
