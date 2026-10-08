"""Start the voice standby model only when offline inference needs it.

Only an invocation started by this manager may be released. Existing users of
the shared service and established HTTP connections are left alone.
"""
import json
from pathlib import Path
import subprocess
import threading
import time
import urllib.request


class LocalModel:
    unit='luka-ws-chat.service'

    def __init__(self, runtime, stop, network, busy, memory_min_mib=3500):
        self.file=Path(runtime)/'local_model_owner.json'
        self.stop,self.network,self.busy=stop,network,busy
        self.lock=threading.Lock()
        self.state='not_requested'
        self.memory_min_mib=memory_min_mib
        self.thread=threading.Thread(target=self.monitor,daemon=True)
        self.thread.start()

    def command(self, args):
        return subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=10)

    def invocation(self):
        return self.command(['systemctl','show',self.unit,'-p','InvocationID','--value']).stdout.strip()

    def ensure(self, cancel):
        with self.lock:
            active=self.command(['systemctl','is-active','--quiet',self.unit]).returncode==0
            if not active:
                memory=next(line for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:'))
                if int(memory.split()[1]) < self.memory_min_mib*1024:
                    self.state='insufficient_memory'
                    raise RuntimeError('insufficient memory to start the local model')
                result=self.command(['sudo','-n','systemctl','start',self.unit])
                if result.returncode: raise RuntimeError('local model service did not start')
                self.file.write_text(json.dumps({'invocation':self.invocation()}))
            self.state='loading'
        deadline=time.monotonic()+60
        while time.monotonic()<deadline:
            if cancel.is_set() or self.stop.is_set(): raise InterruptedError('cancelled')
            try:
                with urllib.request.urlopen('http://127.0.0.1:8092/health',timeout=1) as response:
                    if json.load(response).get('status')=='ok':
                        self.state='ready';return
            except OSError: pass
            self.stop.wait(.3)
        self.state='load_timeout'
        raise TimeoutError('local model did not become ready')

    def release(self):
        with self.lock:
            if not self.file.exists(): return
            owned=json.loads(self.file.read_text()).get('invocation')
            if not owned or owned!=self.invocation():
                self.file.unlink(missing_ok=True);return
            clients=self.command(['ss','-H','-nt','state','established','( sport = :8092 or dport = :8092 )'])
            if clients.returncode or clients.stdout.strip(): return
            if self.command(['sudo','-n','systemctl','stop',self.unit]).returncode==0:
                self.file.unlink(missing_ok=True);self.state='standby_not_loaded'

    def monitor(self):
        while not self.stop.wait(5):
            if self.network()=='online' and not self.busy():
                try:self.release()
                except (OSError,ValueError,subprocess.TimeoutExpired):pass

    def close(self):
        self.thread.join(timeout=10)
        self.release()
