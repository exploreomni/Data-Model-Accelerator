"""Dispatch accounting is local coordination, never host execution or approval."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'
sys.path.insert(0, str(SCRIPTS))
import run_control as control


class RunControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / 'source'; self.source.mkdir()
        (self.source / 'orders.sql').write_text('select order_id from orders')
        self.output = self.root / 'candidate'; self.output.mkdir()
        self.state = {'inputs': {'source': {'path': str(self.source)}}, 'answers': {},
                      'workflow': {'tasks': [], 'runs': [], 'design': None}}

    def claim(self, name, **overrides):
        request = {'schema_version': 1, 'work_id': name, 'attempt_id': name + '-1',
                   'role': 'source_specialist', 'scope_ids': [name],
                   'source_paths': ['orders.sql'], **overrides}
        return control.claim_work(self.state, request)

    def checkpoint(self, name, status='interrupted', outputs=None):
        return control.checkpoint_work(self.state, {'schema_version': 1,
            'attempt_id': name + '-1', 'status': status, 'reason': 'Bounded checkpoint',
            'outputs': outputs or []}, self.output)

    def test_ceiling_applies_to_every_specialist_role_and_resume_keeps_completed(self):
        self.claim('extract')
        self.claim('design', role='warehouse_architect')
        with self.assertRaisesRegex(ValueError, 'concurrency'):
            self.claim('topics', role='semantic_modeler')
        self.checkpoint('design')
        (self.output / 'extracted.json').write_text('{"expression":"complete"}')
        self.checkpoint('extract', 'outputs_recorded', ['extracted.json'])
        before = len(self.state['operations']['attempts'])
        reused = self.claim('extract', attempt_id='extract-2')
        self.assertEqual(reused['action'], 'reuse')
        self.assertEqual(len(self.state['operations']['attempts']), before)
        resumed = self.claim('design', attempt_id='design-2', role='warehouse_architect')
        self.assertEqual(resumed['action'], 'dispatch')
        self.assertEqual(resumed['resumes_attempt_id'], 'design-1')
        self.assertEqual(control.public_summary(self.state)['counts']['active'], 1)

    def test_same_active_task_is_reused_without_duplicate_launch(self):
        first = self.claim('extract')
        repeated = self.claim('extract', attempt_id='extract-2')
        self.assertEqual(repeated['action'], 'already_active')
        self.assertEqual(repeated['attempt_id'], first['attempt_id'])
        self.assertEqual(len(self.state['operations']['attempts']), 1)

    def test_output_and_source_drift_prevent_reuse(self):
        self.claim('extract')
        (self.output / 'result.json').write_text('{}')
        self.checkpoint('extract', 'outputs_recorded', ['result.json'])
        (self.output / 'result.json').write_text('{"changed":true}')
        self.assertEqual(self.claim('extract', attempt_id='extract-2')['action'], 'dispatch')
        self.checkpoint_attempt('extract-2')
        (self.source / 'orders.sql').write_text('select order_id, status from orders')
        self.assertEqual(self.claim('extract', attempt_id='extract-3')['action'], 'dispatch')

    def test_renaming_identical_work_cannot_dispatch_duplicate_worker(self):
        first = self.claim('extract', scope_ids=['orders'], source_type='looker')
        second = self.claim('renamed', scope_ids=['orders'], source_type='looker')
        self.assertEqual(second['action'], 'already_active')
        self.assertEqual(second['attempt_id'], first['attempt_id'])
        self.assertEqual(len(self.state['operations']['attempts']), 1)
        (self.output / 'result.json').write_text('{}')
        self.checkpoint('extract', 'outputs_recorded', ['result.json'])
        self.assertEqual(self.claim('renamed', scope_ids=['orders'], source_type='looker')['action'], 'reuse')

    def test_parser_dependency_drift_prevents_reuse(self):
        from unittest.mock import patch
        with patch('source_adapters.registry.component_fingerprint', return_value='a' * 64):
            self.claim('extract', source_type='looker')
            (self.output / 'result.json').write_text('{}')
            self.checkpoint('extract', 'outputs_recorded', ['result.json'])
            self.assertEqual(self.claim('extract', attempt_id='extract-2', source_type='looker')['action'], 'reuse')
        with patch('source_adapters.registry.component_fingerprint', return_value='b' * 64):
            self.assertEqual(self.claim('extract', attempt_id='extract-2', source_type='looker')['action'], 'dispatch')

    def checkpoint_attempt(self, attempt):
        control.checkpoint_work(self.state, {'schema_version': 1, 'attempt_id': attempt,
            'status': 'interrupted', 'reason': 'stop', 'outputs': []}, self.output)

    def test_failed_checkpoint_is_atomic_and_cannot_touch_source(self):
        self.claim('extract')
        before = copy.deepcopy(self.state)
        with self.assertRaises(ValueError):
            self.checkpoint('extract', 'outputs_recorded', ['../source/orders.sql'])
        self.assertEqual(self.state, before)
        with self.assertRaises(ValueError):
            control.checkpoint_work(self.state, {'schema_version': 1, 'attempt_id': 'extract-1',
                'status': 'outputs_recorded', 'reason': 'done', 'outputs': ['orders.sql']}, self.source)
        self.assertEqual(self.state, before)

    def test_missing_outputs_cannot_be_complete_and_legacy_state_stays_readable(self):
        before = copy.deepcopy(self.state)
        summary = control.public_summary(self.state)
        self.assertEqual(summary['status'], 'untracked')
        self.assertEqual(self.state, before)
        self.claim('extract')
        with self.assertRaisesRegex(ValueError, 'output'):
            self.checkpoint('extract', 'outputs_recorded')
        self.assertEqual(self.state['operations']['attempts'][0]['status'], 'active')

    def test_default_model_not_changed_and_public_summary_excludes_paths(self):
        self.claim('design', role='warehouse_architect')
        summary = control.public_summary(self.state)
        self.assertNotIn(str(self.source), str(summary))
        self.assertNotIn('orders.sql', str(summary))
        self.assertIsNone(summary['cost'])
        self.assertFalse(summary['execution_verified'])

    def test_runtime_identity_is_content_pinned(self):
        identity = control.runtime_identity()
        self.assertEqual(len(identity['runtime_sha256']), 64)
        self.assertGreater(identity['file_count'], 5)
        self.assertNotIn('/Users/', str(identity))

    def test_guided_commands_persist_claims_and_checkpoint_without_design(self):
        import guided_workflow as guided
        from test_guided_workflow import BASE, collector
        from unittest.mock import patch
        run = self.root / 'engagement'
        with patch.object(guided, '_assess_repository', collector):
            state = guided.start_engagement(self.source, run, BASE)
            request = {'schema_version': 1, 'work_id': 'read', 'attempt_id': 'read-1',
                       'role': 'source_specialist', 'scope_ids': ['orders'], 'source_paths': ['orders.sql']}
            state = guided.stage_action(run, 'claim-work', document=request)
            self.assertEqual(state['last_work_action']['action'], 'dispatch')
            state = guided.stage_action(run, 'checkpoint-work', artifact_root=self.output,
                document={'schema_version': 1, 'attempt_id': 'read-1', 'status': 'interrupted',
                          'reason': 'Host interrupted', 'outputs': []})
            state = guided.resume_engagement(run)
            self.assertEqual(state['operations']['attempts'][0]['status'], 'interrupted')
            self.assertFalse(state['readiness']['execution_authorized'])
            self.assertTrue(state['runtime_observations'])

    def test_explicit_configuration_cannot_hide_active_workers(self):
        self.claim('one'); self.claim('two')
        with self.assertRaisesRegex(ValueError, 'active workers'):
            control.configure(self.state, {'schema_version': 1, 'max_workers': 1, 'reason': 'smaller'})
        control.configure(self.state, {'schema_version': 1, 'max_workers': 3, 'reason': 'Three independent slices'})
        self.assertEqual(self.claim('three')['action'], 'dispatch')
