"""Read real recorded-search results; never generate object locations with an LLM."""
import json,threading,urllib.request,urllib.parse,queue
from pathlib import Path

def read(path):
    with urllib.request.urlopen('http://127.0.0.1:8091'+path,timeout=3) as r:return json.load(r)

def describe(job,location=False):
    query=job.get('query','物品');hits=job.get('hits') or []
    if not hits:return '暂时没有'+query+'的匹配画面。'
    hit=hits[0];text=f'找到{query}的候选画面了，在录像第{round(hit["seconds"])}秒。'
    if location:
        transform=(hit.get('observation') or {}).get('map_from_base')
        if transform:
            x,y,*_=transform['translation']
            text+=f'当时小车地图坐标为横向{x:.1f}米，纵向{y:.1f}米。这是观察位置，请看截图确认物体。'
        else:text+='这段录像没有保存位置，请看前端截图确认。'
    else:
        context=hit.get('observation') or {}
        text+=('要带你去观察位置吗？确认后请唤醒我，说带我去。' if context.get('map_from_base') and context.get('map_pose_status')=='tf_at_capture_time' else '请看前端截图确认。')
    return text

class ObjectAnnouncer:
    def __init__(self,node,path=None):
        self.node=node;self.path=Path(path or '/home/sunrise/luka_ws/voice_object_notices.json')
        try:self.notified=json.loads(self.path.read_text())
        except (OSError,ValueError):self.notified=[]
        self.latest=None;self.selected_job=None
        threading.Thread(target=self.watch,daemon=True).start()
    def watch(self):
        while not self.node.stop_event.wait(1):
            try:
                job=read('/patrol/status').get('job')
                if not job:continue
                self.latest=job
                if job.get('hits') and self.selected_job is None:self.selected_job=job
                if not job.get('hits') or job['id'] in self.notified:continue
                if getattr(self.node,'mode','wake')=='command':continue
                # Retry on a full queue instead of silently losing the notice.
                text=describe(job)
                try:self.node.speak_queue.put_nowait(text)
                except queue.Full:continue
                self.selected_job=job
                self.notified=(self.notified+[job['id']])[-128:]
                temp=self.path.with_suffix('.tmp');temp.write_text(json.dumps(self.notified));temp.replace(self.path)
                self.node._status('object_found_notice job='+job['id']+' text='+text)
            except Exception as exc:
                # Camera service restart/network outage is retried next cycle.
                self.latest=None
    def answer(self,query=None):
        status=read('/patrol/status');latest=status.get('job') or {}
        query=query or latest.get('query')
        if not query:return '还没有查找记录，请说帮我找，再加物品名称。'
        if latest.get('query')==query and latest.get('hits'):
            self.selected_job=latest;return describe(latest,True)
        for session in status.get('sessions',[]):
            jobs=read('/patrol/searches?session='+urllib.parse.quote(session['id']))
            for job in reversed(jobs):
                if job.get('query')==query and job.get('hits'):
                    self.selected_job=job;return describe(job,True)
        if latest.get('query')==query and latest.get('status')=='searching':return '还在查找'+query+'，找到候选画面就告诉你。'
        return '还没有'+query+'的匹配记录，请说帮我找'+query+'。'
