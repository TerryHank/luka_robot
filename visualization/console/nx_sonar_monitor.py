#!/usr/bin/python3
"""Bounded four-channel diagnostic; temporary pinmux restored on exit."""
import gpiod,time,json,mmap,os,struct,statistics,signal,itertools,socket
from pathlib import Path
# board trigger,echo; GPIO offsets,names; NVIDIA PADCTL addresses
CHANNELS=[(13,16,122,126,'PY.00','PY.04',0x243D030,0x243D020),(7,15,144,85,'PAC.06','PN.01',0x2448030,0x2440020),(29,31,105,106,'PQ.05','PQ.06',0x2430068,0x2430070),(32,33,41,43,'PG.06','PH.00',0x2434080,0x2434040)]
META={(7,15):('左前',.20,.09,.06,0,.08),(29,31):('右前',.20,-.09,.06,0,.08),(32,33):('左侧',.20,.19,.15,90,0),(13,16):('右侧',.20,-.19,.15,-90,0)}
latest={};counts={key:0 for key in META};misses={key:0 for key in META}
def notify(text):
 addr=os.environ.get('NOTIFY_SOCKET')
 if addr:
  with socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM) as sock:sock.connect(addr.replace('@','\0',1) if addr.startswith('@') else addr);sock.send(text.encode())
def publish():
 rows=[];now=time.time()
 for key,meta in META.items():
  item=latest.get(key,{'distance_m':None,'sample_at':0,'status':'waiting'})
  rows.append(dict(item,name=meta[0],pins=list(key),position_from_ground_m=list(meta[1:4]),yaw_deg=meta[4],samples=counts[key],missing=misses[key]))
 target=Path('/run/nx-sonar/status.json');tmp=target.with_suffix('.tmp')
 tmp.write_text(json.dumps({'mode':'monitor_only','motion_control':False,'updated_at':now,'channels':rows},ensure_ascii=False));tmp.replace(target)
def interrupted(*args):raise KeyboardInterrupt()
signal.signal(signal.SIGTERM,interrupted)
chip=gpiod.Chip('gpiochip0');fd=os.open('/dev/mem',os.O_RDWR|os.O_SYNC);pages={};original={};lines=[];pairs=[];results=[]
def page(addr):
 base=addr&~4095
 if base not in pages:pages[base]=mmap.mmap(fd,4096,offset=base)
 return pages[base],addr-base
def read(addr):m,o=page(addr);return struct.unpack_from('<I',m,o)[0]
def write(addr,value):m,o=page(addr);struct.pack_into('<I',m,o,value)
try:
 for bt,be,lt,le,nt,ne,at,ae in CHANNELS:
  t=chip.get_line(lt);e=chip.get_line(le)
  assert t.name()==nt and e.name()==ne
  assert not t.is_used() and not e.is_used(),'Pin occupied'
  e.request(consumer='nx-sonar-four-test',type=gpiod.LINE_REQ_EV_BOTH_EDGES);lines.append((e,False))
  t.request(consumer='nx-sonar-four-test',type=gpiod.LINE_REQ_DIR_OUT,default_vals=[0]);lines.append((t,True))
  original[at]=read(at);original[ae]=read(ae)
  write(ae,(original[ae]&~(1<<10))|(1<<4)|(1<<6))
  write(at,original[at]&~((1<<10)|(1<<4)|(1<<6)))
  pairs.append((bt,be,t,e))
  print(json.dumps({'pins':[bt,be],'original_mux':[hex(original[at]),hex(original[ae])]}),flush=True)
 time.sleep(.2)
 notify("READY=1")
 for cycle in itertools.count():
  for bt,be,t,e in pairs:
   while e.event_wait(sec=0,nsec=0):e.event_read()
   trigger_at=time.perf_counter_ns();t.set_value(1);until=time.perf_counter_ns()+20000
   while time.perf_counter_ns()<until:pass
   t.set_value(0);trigger_us=(time.perf_counter_ns()-trigger_at)/1000;rise=None;distance=None;pulse_us=None;edges=0;end=time.monotonic()+.04
   while time.monotonic()<end:
    if not e.event_wait(sec=0,nsec=2000000):continue
    ev=e.event_read();stamp=ev.sec*1000000000+ev.nsec
    edges+=1
    if ev.type==gpiod.LineEvent.RISING_EDGE:rise=stamp
    elif rise is not None:
     pulse_us=(stamp-rise)/1000;distance=round((stamp-rise)*343/2/1e9,4);break
   key=(bt,be);meta=META[key];counts[key]+=1
   valid=distance is not None and .02<=distance<=5
   if not valid:misses[key]+=1
   clearance=round(distance-meta[5],4) if valid else None
   latest[key]={'distance_m':distance if valid else None,'sample_at':time.time(),'clearance_along_axis_m':clearance,'status':'echo' if valid else 'no_valid_echo','hint':('近距离回波（仅提示）' if clearance is not None and clearance<.3 else '有回波（不代表安全）' if valid else '无有效回波，状态未知')}
   latest[key]['diagnostic']={'reason':'valid' if valid else 'pulse_out_of_range' if distance is not None else 'no_falling_edge' if rise is not None else 'no_rising_edge','raw_distance_m':distance,'echo_pulse_us':pulse_us,'trigger_us':round(trigger_us,1),'edges':edges}
   publish();notify('WATCHDOG=1')
   time.sleep(.1)
finally:
 for line,out in reversed(lines):
  if out:line.set_value(0)
  line.release()
 for addr,value in original.items():write(addr,value)
 for m in pages.values():m.close()
 os.close(fd);chip.close()
 print('Temporary pinmux restored; no navigation enabled',flush=True)
