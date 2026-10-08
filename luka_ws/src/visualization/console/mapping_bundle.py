"""Non-overwriting SLAM exports for the local robot UI."""
import json
import re
import uuid
from datetime import datetime
from pathlib import Path


def save_bundle(root, label, run):
    label = label.strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,48}', label):
        return False, '名称请使用1–48位字母、数字、下划线或短横线。'
    ok, state = run(['lifecycle', 'get', '/slam_toolbox'], timeout=8)
    if not ok or not re.search(r'\bactive\s*\[3\]', state):
        return False, '建图节点尚未激活，不能把旧导航地图误存为新建图。'
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    name = label + '_' + datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:8]
    pending = root / ('.pending_' + name)
    pending.mkdir(exist_ok=False)
    try:
        ok, output = run(['run', 'nav2_map_server', 'map_saver_cli', '-f', str(pending / 'map'),
                          '--ros-args', '-p', 'save_map_timeout:=10.0'], timeout=25)
        if not ok:
            raise ValueError('栅格地图保存失败：' + output[-300:])
        ok, output = run(['service', 'call', '/slam_toolbox/serialize_map',
                          'slam_toolbox/srv/SerializePoseGraph',
                          json.dumps({'filename':str(pending / 'session')})], timeout=35)
        if not ok or not re.search(r'result\s*[=:]\s*0\b', output):
            raise ValueError('建图会话保存失败，未发布为完整地图。')
        required = ['map.yaml', 'map.pgm', 'session.posegraph', 'session.data']
        for filename in required:
            path = pending / filename
            if not path.is_file() or path.stat().st_size == 0:
                raise ValueError('缺少有效文件：' + filename)
        # map_saver writes a relative image basename; reject a dangling absolute
        # pending path before publishing the directory under its final name.
        text = (pending / 'map.yaml').read_text()
        image = re.search(r'^image:\s*(.+)$', text, re.M)
        if not image or image.group(1).strip().strip('"\'') != 'map.pgm':
            raise ValueError('地图图片引用不符合相对路径要求。')
        if not (pending / 'map.pgm').read_bytes().startswith((b'P5', b'P2')):
            raise ValueError('地图图片格式无效。')
        metadata = {'label':label,'created_at':datetime.now().isoformat(),
                    'map':'map.yaml','posegraph':'session.posegraph',
                    'status':'saved_unverified','note':'尚未完成导航验收，不自动替换当前地图。'}
        (pending / 'manifest.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2))
        final = root / name
        pending.rename(final)
        return True, f'完整地图已保存：{final}。旧地图未覆盖，也未自动切换地图。'
    except (OSError, ValueError) as exc:
        return False, f'{exc} 未完成文件保留在 {pending}，不会列为完整地图。'
