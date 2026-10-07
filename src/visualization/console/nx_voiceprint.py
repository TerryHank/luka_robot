"""Device-local speaker candidates. Never used to authorize robot commands."""
import json,sqlite3,time,uuid,queue,threading
from contextlib import contextmanager
from pathlib import Path
import numpy as np
from concurrent.futures import Future

ROOT=Path('/home/sunrise/luka_ws/system/product/voiceprints')
MODEL='/home/sunrise/luka_ws/common/models/voice/speaker/model.onnx'
THRESHOLD=.65
MARGIN=.10

def unit(v):
    a=np.asarray(v,dtype=np.float32)
    if a.ndim!=1 or not np.all(np.isfinite(a)) or np.linalg.norm(a)<1e-6:raise ValueError('无效声纹特征')
    return a/np.linalg.norm(a)

def identify(v,profiles):
    scores=sorted([(float(unit(v)@unit(p['vector'])),p) for p in profiles],key=lambda x:x[0],reverse=True)
    if not scores:return {'state':'unknown','name':None,'reason':'尚未录入声纹'}
    score,p=scores[0];gap=score-scores[1][0] if len(scores)>1 else 1.
    known=score>=THRESHOLD and gap>=MARGIN
    return {'state':'candidate' if known else 'unknown','profile_id':p['id'] if known else None,'name':p['name'] if known else None,'similarity':round(score,3),'reason':'声纹候选，仅供个性化参考' if known else '相似度不足或多人过于相近'}

class VoiceprintStore:
    def __init__(self,root=ROOT):
        root=Path(root);root.mkdir(parents=True,exist_ok=True,mode=0o700);self.path=root/'profiles.sqlite3'
        with self.db() as c:
            c.execute('CREATE TABLE IF NOT EXISTS profiles (id TEXT PRIMARY KEY,name TEXT,owner TEXT,vectors TEXT,expires REAL,ready INTEGER)')
            c.execute('CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY,value TEXT)')
        self.path.chmod(0o600)
    @contextmanager
    def db(self):
        c=sqlite3.connect(str(self.path),timeout=2)
        try:
            with c:yield c
        finally:c.close()
    def pending(self):
        with self.db() as c:r=c.execute('SELECT id,name,vectors FROM profiles WHERE ready=0 AND expires>?',(time.time(),)).fetchone()
        return dict(id=r[0],name=r[1],samples=len(json.loads(r[2]))) if r else None
    def profiles(self):
        with self.db() as c:rows=c.execute('SELECT id,name,vectors FROM profiles WHERE ready=1').fetchall()
        return [dict(id=i,name=n,vector=unit(np.mean(json.loads(v),axis=0))) for i,n,v in rows]
    def begin(self,name,owner):
        if not isinstance(name,str) or not 1<=len(name.strip())<=24:raise ValueError('请输入 1 至 24 字的姓名或称呼')
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute('SELECT 1 FROM profiles WHERE ready=0 AND expires>?',(time.time(),)).fetchone():raise ValueError('已有录入任务，请完成或取消')
            if c.execute('SELECT COUNT(*) FROM profiles').fetchone()[0]>=20:raise ValueError('最多保存 20 个声纹，请先删除不需要的记录')
            if c.execute('SELECT 1 FROM profiles WHERE name=?',(name.strip(),)).fetchone():raise ValueError('该称呼已存在，请使用不同称呼或删除旧记录后重录')
            c.execute('INSERT INTO profiles VALUES (?,?,?,?,?,0)',(uuid.uuid4().hex,name.strip(),str(owner),'[]',time.time()+300))
        return self.pending()
    def add(self,ident,vector):
        v=unit(vector)
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            r=c.execute('SELECT vectors FROM profiles WHERE id=? AND ready=0 AND expires>?',(ident,time.time())).fetchone()
            if not r:raise ValueError('录入已取消或超时，请重新开始')
            samples=json.loads(r[0])
            if samples and float(unit(np.mean(samples,axis=0))@v)<THRESHOLD:raise ValueError('与前一段声音差异较大，请同一人靠近麦克风重试')
            samples.append(v.tolist());ready=len(samples)>=3
            c.execute('UPDATE profiles SET vectors=?,ready=? WHERE id=?',(json.dumps(samples),int(ready),ident))
        return len(samples),ready
    def delete(self,ident,owner):
        with self.db() as c:
            c.execute('PRAGMA secure_delete=ON')
            c.execute('DELETE FROM profiles WHERE id=? AND owner=?',(ident,str(owner)))
            c.execute("DELETE FROM state WHERE key='result'")
    def result(self,data):
        with self.db() as c:c.execute('INSERT OR REPLACE INTO state VALUES (?,?)',('result',json.dumps(dict(data,updated_at=time.time()),ensure_ascii=False)))
    def status(self):
        with self.db() as c:
            rows=c.execute('SELECT id,name,ready,expires,vectors FROM profiles').fetchall()
            result=c.execute("SELECT value FROM state WHERE key='result'").fetchone()
        return {'profiles':[{'id':i,'name':n,'ready':bool(r),'expired':not r and e<time.time(),'samples':len(json.loads(v))} for i,n,r,e,v in rows],
                'pending':self.pending(),'result':json.loads(result[0]) if result else None,'threshold':THRESHOLD,'model_available':Path(MODEL).is_file()}

class VoiceprintWorker:
    def __init__(self,node):
        self.node=node;self.store=VoiceprintStore();self.extractor=None;self.jobs=queue.Queue(maxsize=1)
        threading.Thread(target=self.run,daemon=True).start()
    def submit(self,audio,rate,with_result=False):
        future=Future() if with_result else None
        pending=self.store.pending();profiles=self.store.profiles()
        if not pending and not profiles:
            if future:future.set_result({'state':'unknown'});return future
            return False
        try:self.jobs.put_nowait((audio.copy(),rate,pending,future))
        except queue.Full:
            if future:future.set_result({'state':'unknown','reason':'busy'})
            if pending:self.node.say('声纹正在处理，请稍后再录这一段。')
        return future if with_result else pending is not None
    def embedding(self,audio,rate):
        if not .6<=len(audio)/rate<=15:raise ValueError('语音太短，请说完整一句话')
        if not np.all(np.isfinite(audio)) or np.sqrt(np.mean(audio*audio))<.004:raise ValueError('声音太小，请靠近麦克风重试')
        if np.mean(np.abs(audio)>.99)>.02:raise ValueError('声音失真，请稍微远离麦克风重试')
        if self.extractor is None:
            import sherpa_onnx
            config=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=MODEL,num_threads=1,provider='cpu')
            if not config.validate():raise ValueError('声纹模型尚未就绪')
            self.extractor=sherpa_onnx.SpeakerEmbeddingExtractor(config)
        s=self.extractor.create_stream();s.accept_waveform(sample_rate=rate,waveform=audio);s.input_finished()
        if not self.extractor.is_ready(s):raise ValueError('有效语音不足，请重新录入')
        return unit(self.extractor.compute(s))
    def run(self):
        while not self.node.stop_event.is_set():
            try:audio,rate,pending,future=self.jobs.get(timeout=1)
            except queue.Empty:continue
            started=time.monotonic();result={'state':'unknown'}
            try:
                if pending and len(audio)/rate < 2:
                    raise ValueError('录入声纹请连续说话 3 至 6 秒')
                v=self.embedding(audio,rate)
                if pending:
                    count,ready=self.store.add(pending['id'],v)
                    message='声纹录入完成。' if ready else f'已录入第{count}段，请点击页面录下一段，再说一段不同的话。'
                    self.store.result({'state':'enrollment','name':pending['name'],'reason':message});self.node.say(message)
                else:
                    result=dict(identify(v,self.store.profiles()),seconds=round(time.monotonic()-started,3),audio_s=round(len(audio)/rate,3))
                    self.store.result(result)
            except Exception as exc:
                self.store.result({'state':'unknown','name':None,'reason':str(exc)})
                if pending:self.node.say(str(exc))
            finally:
                if future and not future.done():future.set_result(result)
                self.jobs.task_done()
