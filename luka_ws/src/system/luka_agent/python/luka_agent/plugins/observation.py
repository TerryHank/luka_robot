import subprocess
from pathlib import Path
from luka_agent.registry import Capability
from luka_agent.plugins.readiness import vision_ready


def vision(context, action, args):
    from nx_patrol_mission import vision as request
    node = context['node']
    if action != 'status' and (node.patrol_mission.active() or node.nx_handle is not None):
        raise ValueError('another_base_task_active')
    endpoint = {'status': '/patrol/status', 'start': '/patrol/start', 'stop': '/patrol/stop', 'locate': '/locate'}[action]
    return dict(state='SUCCEEDED' if action == 'status' else 'ACCEPTED', result=request(endpoint, args))


def voice_volume(context, args):
    current = subprocess.run(['amixer', '-c', 'Device', 'sget', 'PCM'], capture_output=True, text=True, timeout=3)
    if current.returncode: raise ValueError('speaker_mixer_unavailable')
    import re
    values = re.findall(r'\[(\d+)%\]', current.stdout)
    if not values: raise ValueError('speaker_volume_unknown')
    target = args.get('volume')
    if target is None:
        if args.get('direction') not in ('up', 'down'): raise ValueError('volume_or_direction_required')
        target = max(0, min(100, int(values[0]) + (10 if args['direction'] == 'up' else -10)))
    elif 'direction' in args: raise ValueError('ambiguous_volume_arguments')
    result = subprocess.run(['amixer', '-c', 'Device', 'sset', 'PCM', str(target) + '%', 'unmute'], capture_output=True, timeout=3)
    if result.returncode: raise ValueError('speaker_volume_failed')
    return dict(state='SUCCEEDED', volume=target, message='说话音量已设为' + str(target))


def voiceprint(context, args):
    from nx_voiceprint import VoiceprintStore
    return dict(state='SUCCEEDED', result=VoiceprintStore().status())


def register(registry):
    def observe_vision(ctx, value):
        from nx_patrol_mission import vision as request
        return dict(value, state='UNKNOWN', observation=request('/patrol/status'),
                    message='已提交请求，现有接口尚未提供与此任务关联的完成确认')
    text = {'type': 'string', 'minLength': 1, 'maxLength': 80}
    registry.register(Capability('robot_status', '读取当前任务、定位和功能运行状态',
        lambda ctx, args: dict(state='SUCCEEDED', mission=ctx['node'].patrol_mission.snapshot(), localization=ctx['node'].product.localization_status())))
    registry.register(Capability('functions_status', '读取已有功能服务状态',
        lambda ctx, args: dict(state='SUCCEEDED', result=ctx['node'].function_start.status())))
    registry.register(Capability('camera_find', '提交当前相机画面物品识别，不导航',
        lambda ctx, args: vision(ctx, 'locate', args), {'query': text}, ('query',), resources=('vision',), mutation=True, observe=observe_vision, ready=vision_ready))
    for name, action in [('record_start', 'start'), ('record_stop', 'stop'), ('record_status', 'status')]:
        registry.register(Capability(name, {'start': '原地开始录像', 'stop': '停止并保存录像', 'status': '查询真实录像状态'}[action],
            lambda ctx, args, action=action: vision(ctx, action, args), mutation=action != 'status', observe=observe_vision if action != 'status' else None, ready=vision_ready))
    registry.register(Capability('voice_volume', '设置说话输出音量，或按direction相对增减', voice_volume,
        {'volume': {'type': 'integer', 'minimum': 0, 'maximum': 100}, 'direction': {'type': 'string', 'enum': ['up', 'down']}}, resources=('speaker_volume',), mutation=True))
    registry.register(Capability('voiceprint_status', '查询声纹数量和最近候选，不作为身份认证', voiceprint))
    registry.register(Capability('doa_status', '查询最近硬件唤醒的声源方向，不移动机器人',
        lambda ctx, args: dict(state='SUCCEEDED', event=__import__('json').loads(Path('/home/sunrise/luka_data/runtime/audio/xfm_doa.json').read_text()))))
    registry.register(Capability('settings_help', '介绍现有能力及设置入口，不执行操作',
        lambda ctx, args: dict(state='SUCCEEDED', capabilities=[{key: row.get(key) for key in ('name', 'description', 'ready', 'reason')} for row in registry.describe(ctx)]), {'topic': text}))
