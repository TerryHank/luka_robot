"""Voice lookup through the map-scoped mission; legacy video formatter is explicit-only."""
import json,threading,urllib.request,urllib.error,urllib.parse,queue
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
    """Semantic replies come from the mission once; no second polling announcement."""
    def __init__(self,node,path=None):
        self.node=node
    def answer(self,query=None):
        body={'tool':'object_where','arguments':{'query':query} if query else {},
              'source':query+'在哪里' if query else '东西在哪'}
        req=urllib.request.Request('http://127.0.0.1:8503/api/assistant/execute',data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(req,timeout=12) as response:result=json.load(response)
        except urllib.error.HTTPError as exc:
            try:message=json.loads(exc.read()).get('error','无法读取物体记忆')
            except ValueError:message='无法读取物体记忆'
            raise ValueError(message) from exc
        if not result.get('ok'):raise ValueError(result.get('error','无法读取物体记忆'))
        return result['message']
