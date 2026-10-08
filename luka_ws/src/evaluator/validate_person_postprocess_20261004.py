import io,json,time,statistics,urllib.request,sys,importlib.util
from pathlib import Path
import cv2,numpy as np
ROOT=Path('/home/sunrise/luka_ws/perception/person_follow');sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'bpu_yolo26_runtime'))
from yolo26_bpu_person import Yolo26PersonSegmenter
cv2.setNumThreads(1);model=Yolo26PersonSegmenter().model
spec=importlib.util.spec_from_file_location('reference_yolo26_seg','/home/sunrise/luka_migration_backups/bpu_postprocess_20261004/bpu_yolo26_runtime/yolo26_seg.py')
reference=importlib.util.module_from_spec(spec);sys.modules[spec.name]=reference;spec.loader.exec_module(reference)
old=reference.YOLO26Seg.__new__(reference.YOLO26Seg);old.__dict__.update(model.__dict__)
images={'live_scene':cv2.imread('/home/sunrise/luka_ws/evaluator/profile_live_scene_20261004.jpg')}
for name in ['bus','zidane']:images[name]=cv2.resize(cv2.imread(str(ROOT/f'models/bpu_yolo26/cal_images/{name}.jpg')),(640,480))
results={}
for name,image in images.items():
 out=model.forward(model.pre_process(image));before=old.post_process(out,640,480);after=model.post_process(out,640,480)
 ids=np.where(before[2]==0)[0]
 assert len(ids)==len(after[2]),name
 assert np.all(after[2]==0),name
 if len(ids):
  assert np.allclose(before[0][ids],after[0],atol=1e-4,rtol=0),name
  assert np.allclose(before[1][ids],after[1],atol=1e-6,rtol=0),name
 ious=[]
 for i,j in enumerate(ids):
  a,b=before[3][j],after[3][i];assert a.shape==b.shape,(name,a.shape,b.shape)
  union=np.count_nonzero(a|b);iou=np.count_nonzero(a&b)/union if union else 1.0
  assert iou>.999,(name,iou);ious.append(iou)
 timings={}
 for label,fn in [('before',old.post_process),('after',model.post_process)]:
  values=[]
  for i in range(15):
   t=time.perf_counter();fn(out,640,480);elapsed=time.perf_counter()-t
   if i>=3:values.append(elapsed*1000)
  timings[label+'_post_ms']=statistics.median(values)
 results[name]=dict(all_masks_before=len(before[2]),person_masks_after=len(after[2]),mask_ious=ious,**timings)
results['pass']=True
Path('/home/sunrise/luka_ws/evaluator/person_postprocess_validation_20261004.json').write_text(json.dumps(results,indent=2))
print(json.dumps(results,indent=2))
