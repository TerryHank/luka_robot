import datetime
import json
import pathlib
import sqlite3
import time
import uuid
import numpy as np

CHINESE = dict(zip(
    'person,bicycle,car,motorcycle,airplane,bus,train,truck,boat,traffic light,fire hydrant,stop sign,parking meter,bench,bird,cat,dog,horse,sheep,cow,elephant,bear,zebra,giraffe,backpack,umbrella,handbag,tie,suitcase,frisbee,skis,snowboard,sports ball,kite,baseball bat,baseball glove,skateboard,surfboard,tennis racket,bottle,wine glass,cup,fork,knife,spoon,bowl,banana,apple,sandwich,orange,broccoli,carrot,hot dog,pizza,donut,cake,chair,couch,potted plant,bed,dining table,toilet,tv,laptop,mouse,remote,keyboard,cell phone,microwave,oven,toaster,sink,refrigerator,book,clock,vase,scissors,teddy bear,hair drier,toothbrush'.split(','),
    '人,自行车,汽车,摩托车,飞机,公交车,火车,卡车,船,红绿灯,消防栓,停车标志,停车计时器,长凳,鸟,猫,狗,马,羊,牛,大象,熊,斑马,长颈鹿,背包,雨伞,手提包,领带,行李箱,飞盘,滑雪板,单板滑雪板,球,风筝,棒球棒,棒球手套,滑板,冲浪板,网球拍,瓶子,高脚杯,杯子,叉子,刀,勺子,碗,香蕉,苹果,三明治,橙子,西兰花,胡萝卜,热狗,披萨,甜甜圈,蛋糕,椅子,沙发,盆栽,床,餐桌,马桶,电视,笔记本电脑,鼠标,遥控器,键盘,手机,微波炉,烤箱,烤面包机,水槽,冰箱,书,时钟,花瓶,剪刀,泰迪熊,吹风机,牙刷'.split(',')))
ALIASES = {v:k for k,v in CHINESE.items()}
ALIASES.update({'水杯':'cup','茶杯':'cup','杯':'cup','水瓶':'bottle','瓶':'bottle','书本':'book','书籍':'book','椅':'chair','桌子':'dining table','桌':'dining table','显示器':'tv','电脑':'laptop','绿植':'potted plant','植物':'potted plant','电话':'cell phone','背袋':'backpack'})


def overlap(a,b):
    intersection = max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
    union = (a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-intersection
    return intersection/max(1,union)


class Memory:
    def __init__(self,path):
        self.path = pathlib.Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE IF NOT EXISTS objects (id TEXT PRIMARY KEY, frame TEXT NOT NULL, class TEXT NOT NULL, first_seen REAL NOT NULL, last_seen REAL NOT NULL, hits INTEGER NOT NULL, payload TEXT NOT NULL)')
            db.execute('CREATE INDEX IF NOT EXISTS idx_frame ON objects(frame,last_seen)')
            db.execute('CREATE TABLE IF NOT EXISTS observations (id INTEGER PRIMARY KEY, object_id TEXT, ts REAL, payload TEXT)')
            db.execute('CREATE INDEX IF NOT EXISTS idx_obs_ts ON observations(ts)')
        self.last_history = {}

    def connect(self):
        return sqlite3.connect(self.path,timeout=10)

    def update(self,detections,frame,ts):
        with self.connect() as db:
            rows = db.execute('SELECT id,first_seen,last_seen,hits,payload FROM objects WHERE frame=? ORDER BY last_seen DESC LIMIT 5000',(frame,)).fetchall()
            candidates = [(r,json.loads(r[4])) for r in rows]
            used = set()
            output = []
            for detection in sorted(detections,key=lambda d:-d['confidence']):
                choices = []
                for row,old in candidates:
                    if row[0] in used or old['class']!=detection['class']:
                        continue
                    iou = overlap(old['bbox'],detection['bbox'])
                    a,b = old.get('xyz_m'),detection.get('xyz_m')
                    distance = np.linalg.norm(np.array(a)-np.array(b)) if a and b else None
                    if distance is not None and distance>.4:
                        continue
                    if iou>=.3 or (distance is not None and distance<.18 and iou>.05):
                        choices.append((iou+(0 if distance is None else max(0,.2-distance)),row))
                if choices:
                    row = max(choices,key=lambda item:item[0])[1]
                    oid,first,hits = row[0],row[1],row[3]+1
                    # A candidate must be observed repeatedly without a long gap.
                    if row[3]<3 and ts-row[2]>5:
                        hits,first = 1,ts
                else:
                    oid,first,hits = uuid.uuid4().hex[:16],ts,1
                used.add(oid)
                result = dict(detection,id=oid,frame=frame,first_seen=first,last_seen=ts,hits=hits)
                result['label_zh'] = CHINESE.get(result['class'],result['class'])
                result['snapshot'] = f'/objects/{oid}.jpg'
                db.execute('INSERT INTO objects VALUES (?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET last_seen=excluded.last_seen,hits=excluded.hits,first_seen=excluded.first_seen,payload=excluded.payload',
                           (oid,frame,result['class'],first,ts,hits,json.dumps(result,ensure_ascii=False)))
                if hits>=3 and ts-self.last_history.get(oid,0)>=10:
                    db.execute('INSERT INTO observations(object_id,ts,payload) VALUES (?,?,?)',(oid,ts,json.dumps(result,ensure_ascii=False)))
                    self.last_history[oid]=ts
                output.append(result)
            db.execute('DELETE FROM objects WHERE hits<3 AND last_seen<?',(ts-60,))
        return output

    def cleanup(self,ts):
        with self.connect() as db:
            db.execute('DELETE FROM observations WHERE ts<?',(ts-30*86400,))

    def search(self,query='',frame=None,limit=30):
        query = query.strip().lower()
        interpreted = None
        if query:
            for alias,cls in sorted({**ALIASES,**{k:k for k in CHINESE}}.items(),key=lambda p:-len(p[0])):
                if alias in query:
                    interpreted = cls
                    break
        with self.connect() as db:
            sql = 'SELECT payload FROM objects WHERE hits>=3'
            args = []
            if frame:
                sql+=' AND frame=?';args.append(frame)
            if query:
                sql+=' AND class=?';args.append(interpreted or query)
            sql+=' ORDER BY last_seen DESC LIMIT ?';args.append(max(1,min(limit,200)))
            results = [json.loads(r[0]) for r in db.execute(sql,args)]
        now = time.time()
        for obj in results:
            obj['age_seconds'] = round(max(0,now-obj['last_seen']),1)
            obj['recently_seen'] = obj['age_seconds']<=5
            obj['last_seen_local'] = datetime.datetime.fromtimestamp(obj['last_seen']).astimezone().isoformat(timespec='seconds')
            center = (obj['bbox'][0]+obj['bbox'][2])/2
            vertical = (obj['bbox'][1]+obj['bbox'][3])/2
            obj['image_location_zh'] = ('左' if center<640/3 else '右' if center>640*2/3 else '中')+('上方' if vertical<160 else '下方' if vertical>320 else '部')
        return {'query':query,'interpreted_class':interpreted,'count':len(results),'objects':results,
                'scope':'固定相机坐标；按类别和位置关联，不保证同类物体的个体身份。距离是检测框中央表面的估计值。'}
