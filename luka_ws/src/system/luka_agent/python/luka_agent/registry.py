"""Discover business plugins; execution checks are independent of user wording."""
from dataclasses import dataclass, field
import importlib
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
import uuid


def validate_value(value, schema, name='arguments'):
    kind = schema.get('type')
    types = {'object': dict, 'array': list, 'string': str, 'integer': int,
             'number': (int, float), 'boolean': bool}
    if kind in types and (not isinstance(value, types[kind]) or kind in ('integer', 'number') and isinstance(value, bool)):
        raise ValueError(name + ': invalid parameter type')
    if 'enum' in schema and value not in schema['enum']:
        raise ValueError(name + ': unsupported value')
    if kind == 'object':
        properties = schema.get('properties', {})
        if any(k not in value for k in schema.get('required', [])):
            raise ValueError(name + ': missing required parameter')
        if schema.get('additionalProperties') is False and set(value) - set(properties):
            raise ValueError(name + ': unknown parameter')
        for key, item in value.items():
            if key in properties:
                validate_value(item, properties[key], name + '.' + key)
    if kind == 'array':
        if not schema.get('minItems', 0) <= len(value) <= schema.get('maxItems', 1000):
            raise ValueError(name + ': invalid item count')
        for item in value:
            validate_value(item, schema.get('items', {}), name)
    if kind == 'string' and not schema.get('minLength', 0) <= len(value) <= schema.get('maxLength', 100000):
        raise ValueError(name + ': invalid text length')
    if kind in ('integer', 'number'):
        import math
        if not math.isfinite(value) or value < schema.get('minimum', -float('inf')) or value > schema.get('maximum', float('inf')):
            raise ValueError(name + ': parameter outside range')


@dataclass
class Capability:
    name: str
    description: str
    handler: object
    properties: dict = field(default_factory=dict)
    required: tuple = ()
    resources: tuple = ()
    mutation: bool = False
    motion: bool = False
    cancel: bool = False
    ready: object = None
    observe: object = None

    @property
    def schema(self):
        return dict(type='object', properties=self.properties, required=list(self.required), additionalProperties=False)


class Registry:
    def __init__(self, runtime=None, motion_enabled=None):
        self.tools = {}
        self.motion_enabled = os.getenv('LUKA_AGENT_MOTION_ENABLED', 'false') == 'true' if motion_enabled is None else motion_enabled
        self.runtime = Path(runtime or '/home/sunrise/luka_data/runtime/agent/backend')
        self.runtime.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.resources = {}
        self.versions = {}
        self.replay = {}
        self.cancellations = {}
        self.db = sqlite3.connect(self.runtime / 'operations.sqlite3', check_same_thread=False)
        self.db.execute('CREATE TABLE IF NOT EXISTS operations (id TEXT PRIMARY KEY, fingerprint TEXT, task TEXT, tool TEXT, state TEXT, result TEXT, updated REAL)')
        self.db.execute("UPDATE operations SET state='UNKNOWN' WHERE state IN ('RUNNING','ACCEPTED')")
        self.db.commit()

    def register(self, capability):
        if capability.name in self.tools:
            raise ValueError('duplicate capability: ' + capability.name)
        self.tools[capability.name] = capability

    def describe(self, context=None):
        rows = []
        for tool in self.tools.values():
            ready = {'ready': True}
            if tool.motion and not self.motion_enabled:
                ready = {'ready': False, 'reason': 'motion_disabled_pending_live_validation'}
            elif context and tool.ready:
                try: ready = tool.ready(context)
                except Exception: ready = {'ready': False, 'reason': 'dependency_unavailable'}
            rows.append(dict(name=tool.name, description=tool.description, input_schema=tool.schema,
                             resources=list(tool.resources), mutation=tool.mutation, motion=tool.motion,
                             cancel=tool.cancel,
                             side_effect_class='runtime_state', **ready))
        return rows

    def operation(self, operation_id, context=None):
        with self.lock:
            row = self.db.execute('SELECT tool,state,result,task FROM operations WHERE id=?', (operation_id,)).fetchone()
            if not row:
                raise ValueError('unknown operation')
            tool, state, result, task = row
            result = json.loads(result)
            if state in ('ACCEPTED', 'CANCEL_REQUESTED') and context:
                capability = self.tools.get(tool)
                resolver = capability.observe if capability else None
                if resolver:
                    result = resolver(context, result)
                elif context.get('operation_status'):
                    result = context['operation_status'](tool, result)
                    resolver = True
                if resolver:
                    state = result.get('state', state)
                    self._save(operation_id, state, result)
                    if state not in ('RUNNING', 'ACCEPTED'):
                        self._release(operation_id)
            return dict(operation_id=operation_id, task_id=task, tool=tool, state=state, result=result)

    def cancel_task(self, task_id, context):
        self.cancellations.setdefault(task_id, threading.Event()).set()
        with self.lock:
            rows = self.db.execute('SELECT id,tool,state FROM operations WHERE task=?', (task_id,)).fetchall()
        base = any(self.tools.get(name) and self.tools[name].motion and state in ('RUNNING', 'ACCEPTED', 'UNKNOWN') for _, name, state in rows)
        music = any(name == 'music_play' and state == 'SUCCEEDED' for _, name, state in rows)
        if base: context['cancel_all']()
        if music and context.get('music_owner') == task_id: context['music'].action('stop', {})
        with self.lock:
            for operation_id, _, state in rows:
                if state in ('RUNNING', 'ACCEPTED', 'UNKNOWN'):
                    self._save(operation_id, 'CANCEL_REQUESTED', {'state': 'CANCEL_REQUESTED', 'message': '已请求取消，等待执行端停止确认'})
        return dict(state='CANCEL_REQUESTED', message='已请求取消当前任务；停止确认以执行端反馈为准')

    def _save(self, operation_id, state, result):
        self.db.execute('UPDATE operations SET state=?,result=?,updated=? WHERE id=?',
                        (state, json.dumps(result, ensure_ascii=False), time.time(), operation_id))
        self.db.commit()

    def _release(self, operation_id):
        self.resources = {key: value for key, value in self.resources.items() if value != operation_id}

    def execute(self, name, arguments, context, operation_id=None, task_id='web'):
        tool = self.tools.get(name)
        if tool is None:
            raise ValueError('capability is not installed')
        validate_value(arguments, tool.schema)
        if tool.motion and not self.motion_enabled:
            raise ValueError('motion_disabled_pending_live_validation')
        if tool.ready:
            ready = tool.ready(context)
            if not ready.get('ready'):
                raise ValueError(ready.get('reason', 'dependency_unavailable'))
        operation_id = operation_id or uuid.uuid4().hex
        cancellation = self.cancellations.setdefault(task_id, threading.Event())
        if cancellation.is_set(): raise ValueError('task_cancelled')
        context = dict(context, cancel=cancellation)
        fingerprint = json.dumps([name, arguments], sort_keys=True, ensure_ascii=False)
        replay_key = (task_id, fingerprint)
        with self.lock:
            existing = self.db.execute('SELECT fingerprint FROM operations WHERE id=?', (operation_id,)).fetchone()
            if existing:
                if existing[0] != fingerprint: raise ValueError('operation id reused with different arguments')
                return self.operation(operation_id, context)
            prior = self.replay.get(replay_key)
            versions = tuple(self.versions.get(resource, 0) for resource in tool.resources)
            if tool.mutation and prior and prior[1] == versions:
                return dict(self.operation(prior[0], context), replayed=True)
            if any(resource in self.resources for resource in tool.resources):
                raise ValueError('resource_busy')
            for resource in tool.resources: self.resources[resource] = operation_id
            self.db.execute('INSERT INTO operations VALUES (?,?,?,?,?,?,?)',
                            (operation_id, fingerprint, task_id, name, 'RUNNING', '{}', time.time()))
            self.db.commit()
        try:
            value = tool.handler(context, arguments)
            result = value if isinstance(value, dict) else dict(state='SUCCEEDED', message=str(value))
            state = result.get('state', 'SUCCEEDED')
            with self.lock:
                self._save(operation_id, state, result)
                if tool.mutation and state in ('SUCCEEDED', 'ACCEPTED'):
                    for resource in tool.resources: self.versions[resource] = self.versions.get(resource, 0) + 1
                    self.replay[replay_key] = (operation_id, tuple(self.versions.get(r, 0) for r in tool.resources))
                if state != 'ACCEPTED': self._release(operation_id)
            return self.operation(operation_id)
        except Exception as error:
            with self.lock:
                self._save(operation_id, 'FAILED', dict(state='FAILED', message=str(error)))
                self._release(operation_id)
            raise


def discover(runtime=None, motion_enabled=None):
    registry = Registry(runtime, motion_enabled)
    folder = Path(__file__).parent / 'plugins'
    for file in sorted(folder.glob('*.py')):
        if file.name.startswith('_'): continue
        module = importlib.import_module('luka_agent.plugins.' + file.stem)
        module.register(registry)
    return registry
