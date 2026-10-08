import json
import os
import pathlib
import resource
import signal
import subprocess
import time

root=pathlib.Path(__file__).resolve().parent
results=root/'results'
command=[str(root/'build/locate-trial'),str(root/'models/locate-anything-q4_k.gguf'),
         str(root/'runtime/tests/fixtures/parity_image.png'),
         'Locate all the instances that matches the following description: cat</c>remote.',str(results/'fixture'),
         str(results/'desk_448.jpg'),
         'Locate a single instance that matches the following description: computer mouse.',str(results/'mouse'),
         str(results/'desk_448.jpg'),
         'Locate a single instance that matches the following description: lighter.',str(results/'lighter')]
environment=os.environ.copy()
environment['LD_LIBRARY_PATH']='/usr/local/cuda/lib64:/usr/lib/aarch64-linux-gnu/nvidia'
environment['LA_DEVICE']='CUDA0'
def memory():
    return {line.split(':')[0]:int(line.split()[1]) for line in pathlib.Path('/proc/meminfo').read_text().splitlines()}
start=time.monotonic()
initial=memory()
report={'command':command,'initial_memory_kib':initial,'min_available_kib':initial['MemAvailable'],'max_process_rss_kib':0,'samples':[]}
with (results/'run.log').open('w') as log:
    proc=subprocess.Popen(command,cwd=root,env=environment,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    print('INFERENCE_PID',proc.pid,flush=True)
    try:
        while proc.poll() is None:
            mem=memory()
            rss=0
            try:
                for line in pathlib.Path(f'/proc/{proc.pid}/status').read_text().splitlines():
                    if line.startswith('VmRSS:'): rss=int(line.split()[1])
            except FileNotFoundError: pass
            age=time.monotonic()-start
            report['min_available_kib']=min(report['min_available_kib'],mem['MemAvailable'])
            report['max_process_rss_kib']=max(report['max_process_rss_kib'],rss)
            report['samples'].append({'seconds':round(age,1),'rss_kib':rss,'available_kib':mem['MemAvailable'],'swap_used_kib':mem['SwapTotal']-mem['SwapFree']})
            if len(report['samples'])%20==0:
                print(f'Running {age:.0f}s; process RSS {rss/1048576:.2f} GiB; system available {mem["MemAvailable"]/1048576:.2f} GiB',flush=True)
            reason=None
            if mem['MemAvailable']<768*1024: reason='Available system memory fell below 768 MiB'
            if age>240: reason='Trial exceeded four-minute time limit'
            if reason:
                report['abort_reason']=reason
                os.killpg(proc.pid,signal.SIGTERM)
                try: proc.wait(timeout=8)
                except subprocess.TimeoutExpired: os.killpg(proc.pid,signal.SIGKILL)
                break
            time.sleep(.5)
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid,signal.SIGTERM)
        proc.wait()
report['exit_code']=proc.returncode
report['wall_seconds']=time.monotonic()-start
report['resource_maxrss_kib']=resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
(results/'resource_report.json').write_text(json.dumps(report,indent=2))
print('TRIAL_RESULT',json.dumps({k:v for k,v in report.items() if k not in ('samples','command','initial_memory_kib')}),flush=True)
print((results/'run.log').read_text()[-7000:],flush=True)
raise SystemExit(0 if proc.returncode==0 else 1)
