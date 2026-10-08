"""Compatibility facade over discovered Luka business capabilities."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2] / 'system/luka_agent/python'))
from luka_agent.registry import discover

REGISTRY = discover()
TOOLS = {name: tool.description for name, tool in REGISTRY.tools.items()}


def context(node, catalog, send_nav, music):
    def cancel_all():
        node.patrol_mission.stop()
        node.follow_controller.stop()
        return dict(state='CANCEL_REQUESTED', message='已请求停止导航、巡航和跟随，等待执行端停止确认')

    return dict(node=node, catalog=catalog, send_nav=send_nav, music=music, cancel_all=cancel_all,
                music_owner=getattr(node, 'assistant_music_owner', None))


def describe(node, catalog, send_nav, music):
    return REGISTRY.describe(context(node, catalog, send_nav, music))


def execute_operation(node, tool, args, source, catalog, send_nav, music, operation_id=None, task_id='web'):
    if not isinstance(source, str) or len(source) > 4000: raise ValueError('invalid source context')
    value = REGISTRY.execute(tool, args, context(node, catalog, send_nav, music), operation_id, task_id)
    if tool == 'music_play' and value['state'] == 'SUCCEEDED': node.assistant_music_owner = task_id
    return value


def execute(node, tool, args, source, catalog, send_nav, music):
    value = execute_operation(node, tool, args, source, catalog, send_nav, music)
    return value['result'].get('message') or value['state']


def status(operation_id, node, catalog, send_nav, music):
    return REGISTRY.operation(operation_id, context(node, catalog, send_nav, music))


def cancel_task(task_id, node, catalog, send_nav, music):
    return REGISTRY.cancel_task(task_id, context(node, catalog, send_nav, music))
