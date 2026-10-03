import io,json,time,statistics,urllib.request
import cv2,numpy as np
from vision import FaceFeatures
from appearance import BodyAppearance
raw=urllib.request.urlopen('http://127.0.0.1:8091/api/people/camera?zoom=0').read()
with np.load(io.BytesIO(raw),allow_pickle=False) as p:image=cv2.imdecode(p['jpeg'],cv2.IMREAD_COLOR)
s=json.load(urllib.request.urlopen('http://127.0.0.1:8098/api/people/follow-state'));box=s['tracks'][0]['bbox'] if s['tracks'] else [238,0,322,321]
default=cv2.getNumThreads();results=[]
for threads in [default,1,2]:
 cv2.setNumThreads(threads)
 face=FaceFeatures('models/yunet.onnx','models/sface.onnx');body=BodyAppearance('models/osnet_x0_25_msmt17.onnx')
 fs=[];bs=[]
 for _ in range(6):
  t=time.monotonic();face.face_features(image,box);fs.append(time.monotonic()-t)
  t=time.monotonic();body.embed(image,box);bs.append(time.monotonic()-t)
 results.append(dict(threads=threads,face_median_s=statistics.median(fs[1:]),body_median_s=statistics.median(bs[1:])))
print(json.dumps(results,indent=2))
