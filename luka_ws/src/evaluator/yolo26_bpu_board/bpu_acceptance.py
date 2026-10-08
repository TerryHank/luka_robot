"""Static acceptance of the exact YOLO26 model on S100 BPU."""
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time
import cv2
import numpy as np

root = Path('/home/sunrise/luka_ws/perception/person_follow')
sys.path.insert(0, str(root))
from yolo26_bpu_person import Yolo26PersonSegmenter, HBM
models = root/'models/bpu_yolo26'
runner = Yolo26PersonSegmenter()
model = runner.model
report = {'hbm': str(HBM), 'hbm_sha256': hashlib.sha256(HBM.read_bytes()).hexdigest(),
          'source_pt_sha256': hashlib.sha256(Path('/home/sunrise/yolo26m-objv1-seg.pt').read_bytes()).hexdigest(),
          'runtime': 'hbm_runtime.HB_HBMRuntime', 'bpu_cores': [0], 'person_class_id': 0,
          'model_name': model.model_name, 'fixtures': {}, 'non_motion': True}
for filename in ['bus.jpg', 'zidane.jpg', 'astra_000.jpg']:
    image = cv2.imread(str(models/'cal_images'/filename))
    assert image is not None
    detections = runner.detect(image)
    result = []
    for detection in detections:
        mask = detection['person_mask']
        result.append({'bbox': detection['bbox'], 'confidence': detection['confidence'],
                       'mask_shape': list(mask.shape), 'mask_pixels': int(np.count_nonzero(mask))})
    if filename == 'bus.jpg':
        overlay = image.copy()
        for detection in detections:
            x1,y1,x2,y2 = detection['bbox']
            region = overlay[y1:y2,x1:x2]
            mask = detection['person_mask'].astype(bool)
            region[mask] = (region[mask]*.55 + np.array([0,200,0])*.45).astype(np.uint8)
            cv2.rectangle(overlay,(x1,y1),(x2,y2),(0,255,0),2)
            cv2.putText(overlay,f"person {detection['confidence']:.3f}",(x1,max(20,y1-5)),cv2.FONT_HERSHEY_SIMPLEX,.6,(0,255,0),2)
        cv2.imwrite(str(models/'bpu_bus_person_seg.png'),overlay)
    report['fixtures'][filename] = result
    if filename in ['bus.jpg', 'zidane.jpg']:
        assert len(result) >= 2, (filename, result)
        assert all(item['mask_pixels'] > 0 for item in result)
image = cv2.imread(str(models/'cal_images'/'bus.jpg'))
inputs = model.pre_process(image)
forward_ms = []
for index in range(21):
    start = time.perf_counter()
    outputs = model.forward(inputs)
    if index > 0:
        forward_ms.append((time.perf_counter()-start)*1000)
output_shapes = [list(outputs[model.model_name][name].shape) for name in model.output_names]
assert len(output_shapes) == 10, output_shapes
assert [output_shapes[index][-1] for index in [0,3,6]] == [365,365,365], output_shapes
report['output_shapes'] = output_shapes
report['bpu_forward_ms'] = {'median': statistics.median(forward_ms), 'min': min(forward_ms), 'max': max(forward_ms)}
start = time.perf_counter()
model.post_process(outputs, image.shape[1], image.shape[0])
report['post_process_ms'] = (time.perf_counter()-start)*1000
start = time.perf_counter()
runner.detect(image)
report['end_to_end_ms'] = (time.perf_counter()-start)*1000
baseline = json.loads((models/'raw_onnx_acceptance.json').read_text())['fixture_people']
def iou(a,b):
    left,top,right,bottom = max(a[0],b[0]),max(a[1],b[1]),min(a[2],b[2]),min(a[3],b[3])
    intersection = max(0,right-left)*max(0,bottom-top)
    return intersection/((a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-intersection)
report['bus_float_vs_int8'] = [{'float_score': item['score'],
    'best_box_iou': max((iou(item['bbox'],q['bbox']) for q in report['fixtures']['bus.jpg']),default=0)} for item in baseline]
assert all(item['best_box_iou'] >= .8 for item in report['bus_float_vs_int8'][:3]), report['bus_float_vs_int8']
(models/'bpu_acceptance.json').write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2))