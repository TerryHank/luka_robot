from luka_agent.registry import Capability
from luka_agent.plugins.readiness import music_provider_ready


def register(registry):
    definitions = (
        ('search', '按歌名或歌手搜索音乐', {'query': {'type': 'string', 'minLength': 1, 'maxLength': 80}}, ('query',)),
        ('play', '播放指定歌曲；仅在用户要求的前置任务成功后执行', {'query': {'type': 'string', 'minLength': 1, 'maxLength': 80}}, ('query',)),
        ('pause', '暂停当前音乐', {}, ()), ('resume', '继续播放当前音乐', {}, ()),
        ('stop', '停止音乐', {}, ()), ('status', '查询当前音乐的真实播放状态', {}, ()),
        ('volume', '设置音乐播放器音量，0到100', {'volume': {'type': 'integer', 'minimum': 0, 'maximum': 100}}, ('volume',)),
    )
    for action, description, properties, required in definitions:
        registry.register(Capability('music_' + action, description,
            lambda context, args, action=action: context['music'].action(action, args, cancel=context.get('cancel')), properties, required,
            resources=('music',) if action not in ('status', 'search') else (), mutation=action not in ('status', 'search'),
            ready=music_provider_ready if action in ('search', 'play') else None))
