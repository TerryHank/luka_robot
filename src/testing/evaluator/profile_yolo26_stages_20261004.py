import io,json,time,statistics,urllib.request,sys
from pathlib import Path
import cv2,numpy as np
ROOT=Path('/home/sunrise/luka_ws/perception/person_follow')
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'bpu_yolo26_runtime'))
import yolo26_seg as module
from yolo26_bpu_person import Yolo26PersonSegmenter
cv2.setNumThreads(1)
model=Yolo26PersonSegmenter().model
mask_records=[];original_mask=module.process_mask
def mask_profile(*args,**kwargs):
 t=time.perf_counter();result=original_mask(*args,**kwargs);mask_records.append((len(args[1]),time.perf_counter()-t));return result
module.process_mask=mask_profile
raw=urllib.request.urlopen('http://127.0.0.1:8091/api/people/camera?zoom=0',timeout=2).read()
with np.load(io.BytesIO(raw),allow_pickle=False) as p:live=cv2.imdecode(p['jpeg'],cv2.IMREAD_COLOR)
cv2.imwrite('/home/sunrise/luka_ws/evaluator/profile_live_scene_20261004.jpg',live)
images={'live_scene':live,'bus':cv2.resize(cv2.imread(str(ROOT/'models/bpu_yolo26/cal_images/bus.jpg')),(640,480)),'zidane':cv2.resize(cv2.imread(str(ROOT/'models/bpu_yolo26/cal_images/zidane.jpg')),(640,480))}
results={}
for name,image in images.items():
 samples=[]
 for i in range(15):
  mask_records.clear();t=time.perf_counter();inp=model.pre_process(image);t1=time.perf_counter();out=model.forward(inp);t2=time.perf_counter();boxes,scores,classes,masks=model.post_process(out,640,480);t3=time.perf_counter()
  if i>=3:samples.append({'pre_ms':(t1-t)*1000,'forward_ms':(t2-t1)*1000,'post_ms':(t3-t2)*1000,'total_ms':(t3-t)*1000,'mask_ms':sum(r[1] for r in mask_records)*1000})
 results[name]={k:round(statistics.median(s[k] for s in samples),3) for k in samples[0]}
 results[name].update(mask_count=sum(r[0] for r in mask_records),persons=int(np.count_nonzero(classes==0)),all_detections=len(classes),class_ids=classes.tolist())
Path('/home/sunrise/luka_ws/evaluator/yolo26_stage_baseline_20261004.json').write_text(json.dumps(results,indent=2))
print(json.dumps(results,indent=2))
