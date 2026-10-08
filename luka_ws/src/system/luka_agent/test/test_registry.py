import tempfile
import unittest
from types import SimpleNamespace
from luka_agent.registry import Capability, Registry, discover


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.registry = Registry(self.folder.name, motion_enabled=False)

    def tearDown(self):
        self.registry.db.close()
        self.folder.cleanup()

    def test_schema_rejects_extra_fields_types_and_bounds(self):
        self.registry.register(Capability('level', 'level', lambda ctx, args: 'done',
            {'value': {'type': 'integer', 'minimum': 0, 'maximum': 100}}, ('value',)))
        for args in ({'value': True}, {'value': 101}, {'value': 10, 'shell': 'x'}, {}):
            with self.assertRaises(ValueError): self.registry.execute('level', args, {})

    def test_source_wording_is_not_an_execution_condition(self):
        self.registry.register(Capability('play', 'play', lambda ctx, args: 'done', {'query': {'type': 'string'}}, ('query',)))
        result = self.registry.execute('play', {'query': 'a name resolved from context'}, {})
        self.assertEqual(result['state'], 'SUCCEEDED')

    def test_motion_permission_blocks_before_handler(self):
        calls = []
        self.registry.register(Capability('move', 'move', lambda ctx, args: calls.append(1), motion=True))
        with self.assertRaisesRegex(ValueError, 'motion_disabled'): self.registry.execute('move', {}, {})
        self.assertEqual(calls, [])

    def test_duplicate_operation_id_executes_once_and_rejects_changed_args(self):
        calls = []
        self.registry.register(Capability('effect', 'effect', lambda ctx, args: calls.append(args) or 'done', {'x': {'type': 'integer'}}, ('x',), mutation=True))
        self.registry.execute('effect', {'x': 1}, {}, 'op1', 'task1')
        self.registry.execute('effect', {'x': 1}, {}, 'op1', 'task1')
        with self.assertRaises(ValueError): self.registry.execute('effect', {'x': 2}, {}, 'op1', 'task1')
        self.assertEqual(len(calls), 1)

    def test_same_task_repeated_effect_is_replayed_until_resource_changes(self):
        calls = []
        for name in ('play', 'stop'):
            self.registry.register(Capability(name, name, lambda ctx, args, name=name: calls.append(name) or 'done', resources=('music',), mutation=True))
        self.registry.execute('play', {}, {}, 'a', 'task')
        result = self.registry.execute('play', {}, {}, 'b', 'task')
        self.assertTrue(result['replayed']); self.assertEqual(calls, ['play'])
        self.registry.execute('stop', {}, {}, 'c', 'task')
        self.registry.execute('play', {}, {}, 'd', 'task')
        self.assertEqual(calls, ['play', 'stop', 'play'])

    def test_accepted_operation_holds_resource_until_real_success(self):
        self.registry.register(Capability('job', 'job', lambda ctx, args: {'state': 'ACCEPTED'}, resources=('base',), mutation=True))
        self.registry.execute('job', {}, {}, 'a', 'task')
        with self.assertRaisesRegex(ValueError, 'resource_busy'): self.registry.execute('job', {}, {}, 'b', 'different')
        result = self.registry.operation('a', {'operation_status': lambda name, value: dict(value, state='SUCCEEDED')})
        self.assertEqual(result['state'], 'SUCCEEDED')
        self.registry.execute('job', {}, {}, 'c', 'different')

    def test_restart_marks_inflight_unknown_without_reexecution(self):
        calls = []
        self.registry.register(Capability('job', 'job', lambda ctx, args: calls.append(1) or {'state': 'ACCEPTED'}))
        self.registry.execute('job', {}, {}, 'a')
        self.registry.db.close()
        self.registry = Registry(self.folder.name)
        self.assertEqual(self.registry.operation('a')['state'], 'UNKNOWN')
        self.assertEqual(calls, [1])

    def test_discovery_names_are_unique_and_status_is_fresh(self):
        self.registry.db.close()
        self.registry = discover(self.folder.name)
        rows = self.registry.describe()
        self.assertEqual(len(rows), len({r['name'] for r in rows}))
        self.assertTrue(all(r['side_effect_class'] == 'runtime_state' for r in rows))

    def test_cancel_retains_resource_until_stop_confirmation(self):
        self.registry.motion_enabled = True
        self.registry.register(Capability('job', 'job', lambda ctx, args: {'state': 'ACCEPTED'}, resources=('base',), motion=True))
        self.registry.execute('job', {}, {}, 'a', 'task')
        self.registry.cancel_task('task', {'cancel_all': lambda: None})
        with self.assertRaisesRegex(ValueError, 'resource_busy'): self.registry.execute('job', {}, {}, 'b', 'other')
        self.registry.operation('a', {'operation_status': lambda name, value: dict(value, state='CANCELLED')})
        self.registry.execute('job', {}, {}, 'b', 'other')
