import base64
import json
from pathlib import Path
import subprocess
import time
from urllib.request import urlopen, Request
from urllib.error import HTTPError
root = Path('/home/sunrise/luka_ws/perception/person_follow/models/bpu_yolo26')
def get(port,path):
    return json.load(urlopen(f'http://127.0.0.1:{port}{path}',timeout=10))
def infer(encoded,query):
    request = Request('http://127.0.0.1:8096/infer_image',data=json.dumps({'image_base64':encoded,'query':query}).encode(),headers={'Content-Type':'application/json'})
    return json.load(urlopen(request,timeout=30))
fixture = base64.b64encode((root/'cal_images/bus.jpg').read_bytes()).decode()
result = infer(fixture,'人')
assert len(result['detections']) >= 2, result
assert all(d['class']=='person' for d in result['detections']), result
assert result['backend']=='yolo26m-objv1-seg-person-bpu', result
try:
    infer(fixture,'chair')
    raise AssertionError('Unsupported class accepted')
except HTTPError as exc:
    assert exc.code==422, exc.code
status = get(8097,'/api/people/status')
assert status['active'] and status['error'] is None and status['motion_enabled'] is False, status.get('error')
assert status['person_detector']['active']=='yolo26m_objv1_seg_bpu', status['person_detector']
assert status['person_detector']['classes']==['person']
assert status['camera_age'] < 5, status['camera_age']
live = infer(status['frame_jpeg_base64'],'person')
assert all(d['class']=='person' for d in live['detections'])
health = get(8096,'/health')
assert health['model_loaded'] and health['enabled_classes']==['person']
camera = get(8091,'/health')
assert camera['camera_online'] and camera['camera_error'] is None
assert camera['model_backend']=='yolo26m_objv1_seg_person_bpu'
classes = get(8099,'/classes')
assert classes['classes']==['person'], classes
report = {'fixture_api':result,'live_camera_api':live,'people':{k:status[k] for k in ['active','mode','motion_enabled','camera_age','fps','inference_s','person_detector','error']},'object_api':health,'vision':camera,'live_classes':classes,'unsupported_class_http':422}
(root/'bpu_services_acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps(report,ensure_ascii=False,indent=2))