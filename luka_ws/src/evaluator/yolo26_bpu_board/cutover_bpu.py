from pathlib import Path
import shutil
root = Path('/home/sunrise/luka_ws')
backup = Path('/home/sunrise/luka_migration_backups/yolo26_bpu_20261004')
new_import = ('from yolo26_person import Yolo26PersonSegmenter, MODEL',
              'from yolo26_person import Yolo26PersonSegmenter, MODEL, HBM')
files = {
    'perception/person_follow/yolo26_person.py': None,
    'perception/person_follow/worker.py': [('yolo26m_objv1_seg_cpu', 'yolo26m_objv1_seg_bpu'),
        new_import, ('model=MODEL, classes=', 'model=MODEL, runtime_model=str(HBM), classes=')],
    'perception/object_api/s100_object_api.py': [('yolo26m-objv1-seg-person-cpu', 'yolo26m-objv1-seg-person-bpu'),
        new_import, ('"model": MODEL,', '"model": MODEL, "runtime_model": str(HBM),')],
    'perception/locateanything_trial_20260907/yoloe_bridge.py': [('yolo26m-objv1-seg-person-cpu', 'yolo26m-objv1-seg-person-bpu')],
    'perception/locateanything_trial_20260907/live_app.py': [('yolo26m_objv1_seg_person_cpu', 'yolo26m_objv1_seg_person_bpu')],
    'perception/yoloe26_live/yoloe26_live_api.py': [('YOLO26m objv1 person-only ONNX CPU', 'YOLO26m objv1 person-only S100 BPU')],
}
assert (root/'perception/person_follow/models/bpu_yolo26/bpu_acceptance.json').exists(), 'BPU probe must pass before cutover'
assert not backup.exists(), 'Preserve existing backup; investigate previous cutover'
updates = {}
for relative, replacements in files.items():
    source = root/relative
    text = source.read_text()
    if replacements is None:
        text = '"""YOLO26 person segmentation running on the S100 BPU."""\nfrom yolo26_bpu_person import Yolo26PersonSegmenter, MODEL, HBM\n'
    else:
        for old, new in replacements:
            assert old in text, (relative, old)
            text = text.replace(old, new)
    compile(text, str(source), 'exec')
    updates[relative] = text
for relative, text in updates.items():
    source = root/relative
    target = backup/relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    source.write_text(text)
    print(source)
print('Backup', backup)