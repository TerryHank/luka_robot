import unicodedata
import time
from luka_agent.registry import Capability


def resolve(context, name):
    wanted = unicodedata.normalize('NFKC', name).strip().casefold()
    hits = [row for row in context['catalog'](context['node']) if wanted in {
        unicodedata.normalize('NFKC', str(value)).strip().casefold()
        for value in [row['id'], row['display_name'], *row.get('aliases', [])]}]
    if len(hits) != 1: raise ValueError('destination_not_unique_or_missing')
    return hits[0]


def destinations(context, args):
    rows = context['catalog'](context['node'])
    if args.get('query'):
        rows = [row for row in rows if args['query'] in row['display_name'] or args['query'] in row.get('aliases', [])]
    return dict(state='SUCCEEDED', destinations=rows)


def navigate(context, args):
    if 'name' in args and 'waypoint' in args and args['name'] != args['waypoint']:
        raise ValueError('ambiguous_destination_arguments')
    row = resolve(context, args.get('name', args.get('waypoint', '')))
    node = context['node']
    if node.patrol_mission.active(): raise ValueError('another_base_task_active')
    context['send_nav'](node, row['id'])
    return dict(state='ACCEPTED', destination_id=row['id'], message='已提交前往' + row['display_name'] + '，等待到达反馈')


def stopped(node):
    status = getattr(node, 'assistant_motion', {})
    return time.monotonic() - status.get('at', 0) <= 2 and status.get('linear', 1) <= .01 and status.get('angular', 1) <= .01


def observe_navigation(context, value):
    node = context['node']
    if (node.nx_nav_match or {}).get('id') != value.get('destination_id'):
        return dict(value, state='UNKNOWN', message='执行端目标已变化，不能认定原任务已完成')
    state = {4: 'SUCCEEDED', 5: 'CANCELLED', 6: 'FAILED', 'UNKNOWN': 'UNKNOWN'}.get(node.nx_nav_outcome, 'RUNNING')
    if state == 'CANCELLED' and not stopped(node): state = 'CANCEL_REQUESTED'
    return dict(value, state=state, message=node.nx_status)


def register(registry):
    text = {'type': 'string', 'minLength': 1, 'maxLength': 80}
    registry.register(Capability('destinations', '查询已确认的目的地、稳定ID和名称，可选query搜索', destinations,
                                {'query': text}))
    registry.register(Capability('navigate', '导航到查询所得的唯一目的地。受理不表示到达，必须查询operation_status等待SUCCEEDED', navigate,
                                {'name': text, 'waypoint': text}, resources=('base',), mutation=True, motion=True, observe=observe_navigation))
    registry.register(Capability('operation_status', '重新读取operation_id对应任务的进度，等待SUCCEEDED才执行依赖步骤',
                                lambda ctx, args: registry.operation(args['operation_id'], ctx),
                                {'operation_id': {'type': 'string', 'minLength': 1, 'maxLength': 160}}, ('operation_id',)))
    registry.register(Capability('cancel_all', '取消导航、巡航、找物和跟随，确认执行端停止结果',
                                lambda ctx, args: ctx['cancel_all'](), mutation=True, cancel=True))
    registry.register(Capability('localization_status', '查询真实定位及地图核验结果',
                                lambda ctx, args: dict(state='SUCCEEDED', result=ctx['node'].product.localization_status())))
    def relocalize(ctx, args):
        node = ctx['node']
        if node.patrol_mission.active() or node.nx_handle is not None: raise ValueError('another_base_task_active')
        with node.nx_lock: node.relocalization.start('auto', {})
        return dict(state='ACCEPTED', message='已开始自动重定位，等待核验结果')
    def observe_localization(ctx, value):
        status = ctx['node'].product.localization_status()
        return dict(value, state='SUCCEEDED' if status.get('ready') else 'RUNNING', localization=status)
    registry.register(Capability('localization_auto', '自动重定位，需停止当前任务并等待地图核验', relocalize,
                                resources=('base',), mutation=True, motion=True, observe=observe_localization))
