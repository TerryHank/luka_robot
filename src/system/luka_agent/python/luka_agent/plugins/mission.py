from luka_agent.registry import Capability
from luka_agent.plugins.navigation import resolve, stopped


def route_set(context, args):
    mission = context['node'].patrol_mission
    ids = [resolve(context, name)['id'] for name in args['names']]
    route = mission.route_snapshot()
    mission.save_route(dict(revision=route['revision'], ids=ids, dwell_s=args.get('dwell_s', route['dwell_s'])))
    return '路线已保存，尚未启动巡航。'


def register(registry):
    def observe_mission(ctx, value):
        status = ctx['node'].patrol_mission.snapshot()
        raw = status.get('state', status.get('status'))
        state = {'succeeded': 'SUCCEEDED', 'completed': 'SUCCEEDED', 'failed': 'FAILED', 'cancelled': 'CANCELLED', 'canceled': 'CANCELLED'}.get(raw, 'RUNNING')
        if state == 'CANCELLED' and not stopped(ctx['node']): state = 'CANCEL_REQUESTED'
        return dict(value, state=state, mission=status)
    def observe_follow(ctx, value):
        status = ctx['node'].follow_controller.snapshot()
        state = 'RUNNING' if status.get('enabled') else ('CANCELLED' if stopped(ctx['node']) else 'CANCEL_REQUESTED')
        return dict(value, state=state, follow=status)
    text = {'type': 'string', 'minLength': 1, 'maxLength': 80}
    registry.register(Capability('patrol_start', '按保存路线巡航并更新物体记忆，需等待任务完成',
        lambda ctx, args: dict(state='ACCEPTED', result=ctx['node'].patrol_mission.start()), resources=('base',), mutation=True, motion=True, observe=observe_mission))
    registry.register(Capability('patrol_stop', '停止巡航并保留已保存物体记忆',
        lambda ctx, args: ctx['node'].patrol_mission.stop(), mutation=True, cancel=True))
    registry.register(Capability('patrol_route', '查看当前巡航路线和停留时间',
        lambda ctx, args: dict(state='SUCCEEDED', result=ctx['node'].patrol_mission.route_snapshot())))
    registry.register(Capability('patrol_route_set', '保存明确的巡航目的地顺序；可选停留秒数0到60，不启动巡航', route_set,
        {'names': {'type': 'array', 'items': text, 'minItems': 1, 'maxItems': 30}, 'dwell_s': {'type': 'number', 'minimum': 0, 'maximum': 60}}, ('names',), mutation=True))
    registry.register(Capability('find_object', '使用物体记忆和巡航查找指定物品；需等待任务结果',
        lambda ctx, args: dict(state='ACCEPTED', result=ctx['node'].patrol_mission.search(args['query'])),
        {'query': text}, ('query',), resources=('base',), mutation=True, motion=True, observe=observe_mission))
    registry.register(Capability('object_where', '查询已找到物品的观察位置，不移动机器人',
        lambda ctx, args: ctx['node'].patrol_mission.answer(args.get('query')), {'query': text}))
    registry.register(Capability('object_bring', '带用户到已选定并找到的物品处，不代替房间导航',
        lambda ctx, args: dict(state='ACCEPTED', result=ctx['node'].patrol_mission.bring(args)),
        {'query': text}, resources=('base',), mutation=True, motion=True, observe=observe_mission))
    registry.register(Capability('follow_start', '使用现有跟随模块启动跟随，需要目标选择和感知就绪',
        lambda ctx, args: dict(state='ACCEPTED', result=ctx['node'].follow_controller.start()), resources=('base',), mutation=True, motion=True, observe=observe_follow))
    registry.register(Capability('follow_stop', '请求停止跟随',
        lambda ctx, args: ctx['node'].follow_controller.stop(), mutation=True, cancel=True))
