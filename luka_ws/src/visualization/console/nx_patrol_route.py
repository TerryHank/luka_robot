"""Persistent ordered patrol destinations; saving never starts motion."""
import json, math
from pathlib import Path

class PatrolRoute:
    def __init__(self,path,catalog,floor):
        self.path=Path(path);self.catalog=catalog;self.floor=floor
    def document(self):
        try:return json.loads(self.path.read_text())
        except FileNotFoundError:return {'revision':0,'floor_id':'floor_4','ids':['wp_008','wp_009','wp_010'],'dwell_s':4}
    def resolve(self,doc):
        if doc.get('floor_id')!=self.floor():raise ValueError('路线所属楼层与当前地图不一致，请重新保存')
        ids=doc.get('ids');dwell=doc.get('dwell_s',4)
        if not isinstance(ids,list) or not 1<=len(ids)<=30 or any(not isinstance(i,str) for i in ids):raise ValueError('请选择 1 至 30 个巡航航点')
        if isinstance(dwell,bool) or not isinstance(dwell,(int,float)) or not math.isfinite(dwell) or not 0<=dwell<=60:raise ValueError('停留时间须为 0 至 60 秒')
        catalog={p['id']:p for p in self.catalog()}
        if any(i not in catalog for i in ids):raise ValueError('路线包含已删除、未确认或已更名覆盖的航点，请重新选择并保存')
        return [dict(catalog[i]) for i in ids]
    def snapshot(self):
        doc=self.document();error=None
        try:points=self.resolve(doc)
        except ValueError as exc:points=[];error=str(exc)
        return dict(doc,destinations=self.catalog(),points=points,error=error)
    def save(self,body):
        old=self.document()
        if type(body.get('revision')) is not int or body['revision']!=old['revision']:raise ValueError('路线已被其他页面修改，请刷新路线后重试')
        doc={'revision':old['revision']+1,'floor_id':self.floor(),'ids':body.get('ids'),'dwell_s':body.get('dwell_s',4)}
        self.resolve(doc)
        tmp=self.path.with_suffix('.tmp');tmp.write_text(json.dumps(doc,ensure_ascii=False));tmp.replace(self.path)
        return self.snapshot()
