"""Durable device-local product accounts, onboarding and map drafts."""
import hashlib,hmac,json,secrets,sqlite3,time,threading,math,re,os
from pathlib import Path
from contextlib import contextmanager

class ProductStore:
    def __init__(self,root):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.db=self.root/'product.sqlite3';self.lock=threading.RLock()
        self.code_file=self.root/'pairing_code'
        if not self.code_file.exists():
            fd=os.open(str(self.code_file),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'w') as f:f.write(secrets.token_hex(4).upper())
        with self.connect() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,username TEXT UNIQUE NOT NULL,salt TEXT NOT NULL,password_hash TEXT NOT NULL,created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL,expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS documents(key TEXT PRIMARY KEY,payload TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1);
            CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,at REAL NOT NULL,user_id TEXT,action TEXT NOT NULL,detail TEXT);''')
        os.chmod(self.db,0o600)
    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.db,timeout=5)
        try:
            with db:yield db
        finally:db.close()
    def claimed(self):
        with self.connect() as db:return bool(db.execute('SELECT count(*) FROM users').fetchone()[0])
    def audit(self,user,action,detail=''):
        with self.connect() as db:db.execute('INSERT INTO audit(at,user_id,action,detail) VALUES(?,?,?,?)',(time.time(),user,action,detail))
    def register(self,username,password,pairing_code):
        if not isinstance(username,str) or not re.fullmatch(r'[\w\u4e00-\u9fff-]{3,32}',username):raise ValueError('账号需为 3–32 位字母、数字或中文')
        if not isinstance(password,str) or not 10<=len(password)<=128:raise ValueError('密码需为 10–128 个字符')
        if not isinstance(pairing_code,str) or not hmac.compare_digest(pairing_code.strip().upper(),self.code_file.read_text().strip()):raise ValueError('设备配对码不正确')
        salt=secrets.token_hex(16);digest=self.hash_password(password,salt);uid=secrets.token_hex(16)
        with self.lock,self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT count(*) FROM users').fetchone()[0]:raise ValueError('设备已绑定，请登录现有账号')
            db.execute('INSERT INTO users VALUES(?,?,?,?,?)',(uid,username,salt,digest,time.time()))
        self.audit(uid,'device_claimed');return self.login(username,password)
    @staticmethod
    def hash_password(password,salt):return hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt),n=16384,r=8,p=1).hex()
    def login(self,username,password):
        if not isinstance(password,str) or len(password)>128:raise ValueError('账号或密码不正确')
        with self.connect() as db:row=db.execute('SELECT id,salt,password_hash FROM users WHERE username=?',(username,)).fetchone()
        if not row or not hmac.compare_digest(row[2],self.hash_password(password,row[1])):raise ValueError('账号或密码不正确')
        token=secrets.token_urlsafe(32)
        with self.connect() as db:
            db.execute('DELETE FROM sessions WHERE expires<?',(time.time(),))
            db.execute('INSERT INTO sessions VALUES(?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),row[0],time.time()+43200))
        return token
    def user(self,token):
        if not token:return None
        with self.connect() as db:row=db.execute('SELECT u.id,u.username FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires>?',(hashlib.sha256(token.encode()).hexdigest(),time.time())).fetchone()
        return dict(id=row[0],username=row[1]) if row else None
    def logout(self,token):
        with self.connect() as db:db.execute('DELETE FROM sessions WHERE token_hash=?',(hashlib.sha256(token.encode()).hexdigest(),))
    def get(self,key,default=None):
        with self.connect() as db:row=db.execute('SELECT payload,revision FROM documents WHERE key=?',(key,)).fetchone()
        return dict(data=json.loads(row[0]),revision=row[1]) if row else dict(data=default,revision=0)
    def put(self,key,data,revision,user):
        with self.lock,self.connect() as db:
            db.execute('BEGIN IMMEDIATE');row=db.execute('SELECT revision FROM documents WHERE key=?',(key,)).fetchone();old=row[0] if row else 0
            if revision!=old:raise ValueError('内容已被另一页面修改，请刷新后重试')
            db.execute('INSERT INTO documents VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET payload=excluded.payload,revision=excluded.revision',(key,json.dumps(data,ensure_ascii=False),old+1))
            db.execute('INSERT INTO audit(at,user_id,action,detail) VALUES(?,?,?,?)',(time.time(),user,'save:'+key,str(old+1)))
        return dict(data=data,revision=old+1)

def validate_regions(data,info):
    if not isinstance(data,dict):raise ValueError('地图数据格式错误')
    rooms=data.get('rooms',[]);pois=data.get('pois',[])
    if not isinstance(rooms,list) or not isinstance(pois,list) or len(rooms)>100 or len(pois)>300:raise ValueError('房间或航点数量超限')
    seen=set()
    def point(p):
        if not isinstance(p,list) or len(p)!=2 or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in p):raise ValueError('坐标无效')
        dx=p[0]-info['origin_x'];dy=p[1]-info['origin_y'];a=-info.get('origin_yaw',0)
        x=math.cos(a)*dx-math.sin(a)*dy;y=math.sin(a)*dx+math.cos(a)*dy
        if not (0<=x<=info['width']*info['resolution'] and 0<=y<=info['height']*info['resolution']):raise ValueError('选区超出地图范围')
    for item in rooms+pois:
        if not isinstance(item,dict) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}',str(item.get('id',''))):raise ValueError('区域编号无效')
        if item['id'] in seen:raise ValueError('区域编号重复')
        seen.add(item['id'])
        if not isinstance(item.get('name'),str) or not 1<=len(item['name'].strip())<=40:raise ValueError('名称需为 1–40 字')
        item['name']=item['name'].strip()
        if not isinstance(item.get('confirmed',False),bool):raise ValueError('确认状态无效')
    for room in rooms:
        poly=room.get('polygon',[])
        if not isinstance(poly,list) or not 3<=len(poly)<=100:raise ValueError('房间需要有效边界')
        for p in poly:point(p)
        area=abs(sum(poly[i][0]*poly[(i+1)%len(poly)][1]-poly[(i+1)%len(poly)][0]*poly[i][1] for i in range(len(poly))))/2
        if area<.2:raise ValueError('房间选区太小')
    for poi in pois:
        point(poi.get('position'))
        if poi.get('kind') not in ('room_entry','door','elevator_wait','elevator_entry','home','waypoint'):raise ValueError('航点类型无效')
        yaw=poi.get('yaw',0)
        if not isinstance(yaw,(int,float)) or not math.isfinite(yaw):raise ValueError('航点朝向无效')
    return data
