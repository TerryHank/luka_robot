import io,json,time,statistics,urllib.request
import cv2,numpy as np
from yolo26_bpu_person import Yolo26PersonSegmenter
raw=urllib.request.urlopen('http://127.0.0.1:8091/api/people/camera?zoom=0').read()
with np.load(io.BytesIO(raw),allow_pickle=False) as p:image=cv2.imdecode(p['jpeg'],cv2.IMREAD_COLOR)
model=Yolo26PersonSegmenter(confidence=.35)
import os;print('OPENBLAS_NUM_THREADS',os.getenv('OPENBLAS_NUM_THREADS'))
results=[]
for cv_threads,blas_threads in [(6,None),(1,None),(1,1)]:
 cv2.setNumThreads(cv_threads)
 if True:
  samples=[]
  for _ in range(8):
   t=time.monotonic();rows=model.detect(image);samples.append(time.monotonic()-t)
 results.append(dict(cv_threads=cv_threads,blas_threads=blas_threads,median_s=statistics.median(samples[1:]),max_s=max(samples[1:]),persons=len(rows)))
print(json.dumps(results,indent=2))
