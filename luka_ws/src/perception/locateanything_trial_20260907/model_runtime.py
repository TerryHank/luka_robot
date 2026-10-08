"""One model process, loaded on demand and reaped after idle time."""
import json, os, queue, subprocess, threading, time

class ModelRuntime:
    def __init__(self, root, idle_seconds=30):
        self.root=root; self.idle_seconds=idle_seconds; self.proc=None
        self.guard=threading.Lock(); self.events=None; self.last_used=0
        threading.Thread(target=self.reap,daemon=True).start()
    def reader(self,proc,events):
        for line in proc.stdout:
            try:events.put(json.loads(line))
            except ValueError:pass
        events.put({'event':'exit'})
    def event(self,expected,timeout):
        try:r=self.events.get(timeout=timeout)
        except queue.Empty:raise RuntimeError('模型响应超时')
        if r.get('event')!=expected:raise RuntimeError('模型进程已退出或响应异常')
        return r
    def ensure(self):
        if self.proc is not None and self.proc.poll() is None:return
        self.events=queue.Queue()
        self.proc=subprocess.Popen([str(self.root/'build/locate-live'),str(self.root/'models/locate-anything-q4_k.gguf')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,bufsize=1)
        threading.Thread(target=self.reader,args=(self.proc,self.events),daemon=True).start()
        self.event('loaded',60)
    def locate(self,image,query,prefix):
        with self.guard:
            try:
                self.ensure()
                prompt='Locate all the instances that matches the following description: '+query+'.'
                self.proc.stdin.write(str(image)+'\n'+prompt+'\n'+str(prefix)+'\n');self.proc.stdin.flush()
                self.event('inference',120)
                return json.loads((prefix.with_suffix('.json')).read_text())
            except Exception:
                self.stop_locked();raise
            finally:self.last_used=time.monotonic()
    def stop_locked(self):
        if self.proc is not None:
            if self.proc.poll() is None:
                self.proc.terminate()
                try:self.proc.wait(5)
                except subprocess.TimeoutExpired:self.proc.kill();self.proc.wait()
            self.proc=None
    def unload(self):
        if not self.guard.acquire(False):raise ValueError('模型正在识别，暂时不能卸载')
        try:self.stop_locked()
        finally:self.guard.release()
    def loaded(self):return self.proc is not None and self.proc.poll() is None
    def reap(self):
        while True:
            time.sleep(3)
            if self.guard.acquire(False):
                try:
                    if time.monotonic()-self.last_used>self.idle_seconds:self.stop_locked()
                finally:self.guard.release()
