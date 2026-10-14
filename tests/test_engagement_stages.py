"""Synthetic stage journeys; signatures exercise verification, not live acceptance."""
import base64
import copy
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'
sys.path.insert(0, str(SCRIPTS))
import guided_workflow as guided
import engagement_stages as stages
from ae_common import _json_bytes, hash_json
from test_guided_workflow import collector, BASE

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
except ImportError:
    Ed25519PrivateKey = None


def candidate():
    def entity(name, parents):
        return {'id': name, 'name': name, 'domain': 'commerce', 'layer': 'gold',
                'grain': 'One row per ' + name, 'keys': [name + '_id'],
                'columns': [{'name': name + '_id', 'type': 'integer', 'description': 'Stable entity key'}],
                'depends_on': parents, 'asset_ids': ['report:' + name], 'security': 'No personal fields selected',
                'history': 'Current state', 'disposition': 'create', 'reuse': None,
                'source_paths': [name + '.sql'], 'catalogue_pointers': ['/objects/' + name]}
    return {'schema_version': 1, 'id': 'commerce', 'revision': 1,
            'entities': [entity('customers', []), entity('orders', ['customers']), entity('products', [])],
            'relationships': [{'from': 'orders', 'to': 'customers', 'kind': 'relationship', 'cardinality': 'many_to_one'}],
            'assets': [{'id': 'report:' + name, 'name': name.title(), 'kind': 'report', 'mapping_status': 'verified'}
                       for name in ('customers', 'orders', 'products')],
            'decisions': [], 'existing_models': []}


class StageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.repo = self.root / 'source'; self.repo.mkdir()
        for name in ('customers', 'orders', 'products'):
            (self.repo / (name + '.sql')).write_text('select 1 as ' + name + '_id')
        self.catalogue = self.root / 'catalogue.json'
        self.catalogue.write_text(json.dumps({'objects': {n: {'columns': [n + '_id']} for n in ('customers', 'orders', 'products')}}))
        self.run = self.root / 'engagement'
        self.artifacts = self.root / 'candidate'; self.artifacts.mkdir()
        self.patch = patch.object(guided, '_assess_repository', collector)
        self.patch.start(); self.addCleanup(self.patch.stop)
        answers = {**BASE, 'semantic_target': 'omni', 'migration_scope': 'model_semantic', 'input_handling': 'metadata_only'}
        self.state = guided.start_engagement(self.repo, self.run, answers, self.catalogue)
        self.doc = candidate()
        self.state = self.action('import-design', document=self.doc)
        if Ed25519PrivateKey:
            self.key = Ed25519PrivateKey.generate()
            public = self.key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
            self.policy = self.root / 'policy.json'
            self.policy.write_text(json.dumps({'schema_version': 1, 'kind': 'deployment_runner_policy',
                'runner_id': 'synthetic-review-service', 'mode': 'live', 'allowed_actions': ['publish_pr'],
                'destinations': {'unused': {}}, 'state_root': str(self.root / 'issuer-state'),
                'issuers': {'review-service': {'purposes': ['model_signoff'], 'actors': ['reviewer'],
                                             'public_key': base64.b64encode(public).decode()}}}))

    def action(self, command, **kwargs):
        self.state = guided.stage_action(self.run, command, **kwargs)
        return self.state

    def sign(self, scope, identity='review-1'):
        if not Ed25519PrivateKey:
            self.skipTest('Optional cryptography dependency is required for signed review tests')
        now = datetime.now(timezone.utc)
        payload = {'schema_version': 1, 'kind': 'deployment_attestation', 'purpose': 'model_signoff',
                   'mode': 'live', 'issuer': 'review-service', 'actor': 'reviewer', 'id': identity,
                   'review_reference': 'synthetic://review/' + identity,
                   'issued_at': now.isoformat(), 'expires_at': (now + timedelta(hours=1)).isoformat(),
                   'bindings': stages.review_bindings(self.state, scope)}
        return {'payload': payload, 'signature': base64.b64encode(self.key.sign(_json_bytes(payload))).decode()}

    def approve(self, scope=None, identity='review-1'):
        scope = scope or ['customers', 'orders', 'products']
        envelope = self.sign(scope, identity)
        self.action('approve-design', entities=scope, policy=self.policy, attestation=envelope)

    def tasks(self):
        return {'schema_version': 1, 'tasks': [
            {'id': 'build-' + n, 'stage': 'implementation', 'entity_ids': [n],
             'depends_on': ['build-customers'] if n == 'orders' else [],
             'components': [], 'outputs': [n + '.sql']} for n in ('customers', 'orders', 'products')] + [
            {'id': 'semantic', 'stage': 'semantic', 'entity_ids': ['orders'], 'depends_on': ['build-orders'],
             'components': [], 'outputs': ['orders.topic.yaml']}]}

    def plan(self, tasks=None):
        self.action('plan-tasks', document=tasks, artifact_root=self.artifacts)
        return self.state['workflow']['last_plan']

    def complete(self, task_id):
        plan = self.plan()
        task = next(t for t in plan['tasks'] if t['id'] == task_id)
        spec = next(t for t in self.state['workflow']['tasks'] if t['id'] == task_id)
        for path in spec['outputs']:
            (self.artifacts / path).write_text('Synthetic output for ' + task_id)
        self.action('record-task', artifact_root=self.artifacts, document={
            'task_id': task_id, 'run_id': task_id + '-run', 'plan_sha256': plan['plan_sha256'],
            'fingerprint': task['fingerprint'], 'outputs': stages._output_hashes(self.artifacts, spec['outputs']),
            'evidence_reference': 'synthetic://host/' + task_id})

    def test_design_only_and_forged_approval_never_unlock_code(self):
        self.action('stage', entities=['orders'], stage='design')
        self.assertEqual(list(self.artifacts.iterdir()), [])
        with self.assertRaisesRegex(ValueError, 'design review'):
            self.action('stage', entities=['orders'], stage='implementation')
        self.assertEqual(stages.approved_entities(self.state), set())
        if Ed25519PrivateKey:
            envelope = self.sign(['orders'])
            envelope['payload']['actor'] = 'intruder'
            with self.assertRaises(ValueError):
                self.action('approve-design', entities=['orders'], policy=self.policy, attestation=envelope)

    def test_host_attributed_review_opens_candidates_not_deployment(self):
        request = {'schema_version': 1, 'kind': 'human_design_review', 'decision': 'approve',
                   'reviewer': 'Synthetic business reviewer', 'review_reference': 'synthetic://trusted-host/human-message-1',
                   'bindings': stages.review_bindings(self.state, ['orders'])}
        stale = copy.deepcopy(request)
        stale['bindings']['target_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'stale'):
            self.action('approve-design', entities=['orders'], document=stale)
        path = self.root / 'human-review.json'
        path.write_text(json.dumps(request))
        with redirect_stdout(io.StringIO()):
            code = guided.main(['approve-design', '--run', str(self.run), '--entities', 'orders',
                                '--document', str(path), '--no-render'])
        self.assertEqual(code, 0)
        self.state = guided.load_engagement(self.run)
        self.assertEqual(stages.approved_entities(self.state), {'customers', 'orders'})
        self.assertEqual(self.state['workflow']['approvals'][0]['assurance'], 'host_reported_human_review')
        self.action('stage', entities=['orders'], stage='implementation')
        self.assertFalse(self.state['readiness']['execution_authorized'])
        with self.assertRaisesRegex(ValueError, 'separate signed deployment'):
            self.action('stage', entities=['orders'], stage='deployment')
        self.doc['revision'] += 1
        self.doc['entities'][1]['grain'] = 'One row per order line'
        self.action('import-design', document=self.doc)
        self.assertNotIn('orders', stages.approved_entities(self.state))

    def test_end_to_end_plan_preserves_original_runs_and_tamper_invalidates_children(self):
        self.approve()
        plan = self.plan(self.tasks())
        self.assertEqual({t['id']: t['action'] for t in plan['tasks']}['semantic'], 'blocked')
        for task in ('build-customers', 'build-orders', 'build-products', 'semantic'):
            self.complete(task)
        plan = self.plan()
        self.assertTrue(all(t['action'] == 'reuse' for t in plan['tasks']))
        self.assertEqual(len(self.state['workflow']['runs']), 4)
        self.assertEqual(next(t for t in plan['tasks'] if t['id'] == 'semantic')['original_run_id'], 'semantic-run')
        validation = next(s for s in stages.public_view(self.state)['stages'] if s['id'] == 'validation')
        self.assertEqual(validation['status'], 'not_planned')
        self.assertIn('independent validation', validation['next_action'])
        (self.artifacts / 'orders.sql').write_text('tampered')
        changed = {t['id']: t['action'] for t in self.plan()['tasks']}
        self.assertEqual(changed, {'build-customers': 'reuse', 'build-products': 'reuse', 'build-orders': 'regenerate', 'semantic': 'blocked'})
        with self.assertRaisesRegex(ValueError, 'separate signed deployment'):
            self.action('stage', entities=['orders'], stage='deployment')

    def test_scoped_source_and_definition_changes_keep_unrelated_scope(self):
        self.approve()
        (self.repo / 'orders.sql').write_text('select 2 as orders_id')
        self.state = guided.resume_engagement(self.run)
        self.assertEqual(stages.approved_entities(self.state), {'customers', 'products'})
        self.doc['revision'] += 1
        self.doc['entities'][0]['columns'][0]['description'] = 'Changed business meaning'
        self.action('import-design', document=self.doc)
        self.assertEqual(stages.approved_entities(self.state), {'products'})

    def test_cosmetic_change_keeps_approval(self):
        self.approve()
        self.doc['revision'] += 1
        self.doc['entities'][0]['display_label'] = 'Customer overview'
        self.action('import-design', document=self.doc)
        self.assertEqual(stages.approved_entities(self.state), {'customers', 'orders', 'products'})

    def test_decision_roundtrip_stale_rejected_and_answer_not_approval(self):
        self.doc['revision'] += 1
        self.doc['decisions'] = [{'id': 'calendar', 'question': 'Which calendar?',
            'options': [{'id': 'utc', 'label': 'UTC'}], 'recommendation': 'UTC', 'reviewer_role': 'Business owner',
            'model_ids': ['orders'], 'asset_ids': ['report:orders'], 'blocking_stages': ['design'],
            'rationale': 'Grouping dates changes totals.', 'evidence_summary': 'Two calendar definitions were supplied.'}]
        self.action('import-design', document=self.doc)
        doc = self.state['workflow']['design']
        request = {'schema_version': 1, 'kind': 'decision_responses', 'intent': 'record_answers',
            'engagement_id': self.state['engagement_id'], 'design_id': doc['id'], 'design_revision': doc['revision'],
            'design_sha256': doc['sha256'], 'answers': [{'decision_id': 'calendar', 'answer': 'Use UTC', 'option_id': 'utc', 'rationale': ''}],
            'request_only': True}
        stale = {**request, 'design_revision': 1}
        with self.assertRaisesRegex(ValueError, 'stale'):
            self.action('answer-decisions', document=stale)
        self.action('answer-decisions', document=request)
        self.assertEqual(stages.public_view(self.state)['decisions'][0]['status'], 'answer_recorded')
        with self.assertRaises(ValueError):
            self.action('stage', entities=['orders'], stage='implementation')
        self.approve(['orders'])
        self.assertEqual(stages.public_view(self.state)['decisions'][0]['status'], 'resolved')

    def test_semantic_only_decision_does_not_block_warehouse_design(self):
        self.doc['revision'] += 1
        self.doc['decisions'] = [{'id': 'topic', 'question': 'Which topic grouping?', 'options': [],
            'recommendation': None, 'reviewer_role': 'Semantic owner', 'model_ids': ['orders'], 'asset_ids': [],
            'blocking_stages': ['semantic'], 'rationale': 'Topic organization', 'evidence_summary': 'Not selected yet.'}]
        self.action('import-design', document=self.doc)
        self.approve(['orders'])
        self.action('stage', entities=['orders'], stage='implementation')
        with self.assertRaisesRegex(ValueError, 'answer required'):
            self.action('stage', entities=['orders'], stage='semantic')

    def test_semantic_entrypoint_requires_actual_physical_outputs_and_current_guidance(self):
        self.approve()
        self.assertIn('implementation code', self.state['next_actions'][-1]['action'])
        with self.assertRaisesRegex(ValueError, 'physical implementation'):
            self.action('stage', entities=['orders'], stage='semantic')
        self.plan(self.tasks())
        self.complete('build-customers')
        with self.assertRaisesRegex(ValueError, 'physical implementation'):
            self.action('stage', entities=['orders'], stage='semantic')
        self.complete('build-orders')
        self.action('stage', entities=['orders'], stage='semantic')
        self.complete('build-products'); self.complete('semantic')
        self.assertEqual(stages.public_view(self.state)['current_stage'], 'semantic')
        self.assertIn('products', stages.public_view(self.state)['next_action'])
        self.assertIn('semantic code', self.state['next_actions'][-1]['action'])

    def test_component_changes_and_per_plan_source_cache(self):
        self.approve()
        self.plan(self.tasks())
        for task in ('build-customers', 'build-orders', 'build-products', 'semantic'):
            self.complete(task)
        with patch.object(stages, '_source_hash', wraps=stages._source_hash) as reader:
            stages.plan_tasks(self.state, self.artifacts)
        self.assertEqual(reader.call_count, 3, 'Shared sources should be captured once per plan')
        versions = stages.component_versions()
        versions['packaging'] = 'a' * 64
        with patch.object(stages, 'component_versions', return_value=versions):
            self.assertTrue(all(t['action'] == 'reuse' for t in stages.plan_tasks(self.state, self.artifacts)['tasks']))
        versions['semantic'] = 'b' * 64
        with patch.object(stages, 'component_versions', return_value=versions):
            tasks = {t['id']: t['action'] for t in stages.plan_tasks(self.state, self.artifacts)['tasks']}
            self.assertEqual(tasks['semantic'], 'regenerate')
            self.assertEqual(tasks['build-orders'], 'reuse')
        versions['workflow'] = 'c' * 64
        with patch.object(stages, 'component_versions', return_value=versions):
            self.assertFalse(any(t['action'] == 'reuse' for t in stages.plan_tasks(self.state, self.artifacts)['tasks']))

    def test_reuse_requires_all_compatibility_dimensions(self):
        doc = copy.deepcopy(self.doc)
        doc['existing_models'] = [{'id': 'existing-customers', 'name': 'Customer entity', 'grain': 'Customer',
            'keys': ['customers_id'], 'definitions': 'Customer records', 'history': 'Current state',
            'security': 'Restricted', 'dependencies': [], 'evidence_refs': ['inventory']}]
        doc['entities'][0].update(disposition='reuse', reuse={'existing_id': 'existing-customers',
            'dimensions': {'grain': {'status': 'compatible', 'evidence_refs': ['inventory'], 'explanation': 'Same grain'}},
            'rationale': 'Existing entity appears similar'})
        with self.assertRaisesRegex(ValueError, 'comparison must cover'):
            stages.validate_design(doc)

    def test_cycles_output_overlap_and_semantic_without_physical_binding_rejected(self):
        for mutation in ('cycle', 'overlap', 'semantic'):
            tasks = self.tasks()
            if mutation == 'cycle': tasks['tasks'][0]['depends_on'] = ['build-orders']
            if mutation == 'overlap': tasks['tasks'][1]['outputs'] = ['customers.sql']
            if mutation == 'semantic': tasks['tasks'][-1]['depends_on'] = []
            with self.subTest(case=mutation), self.assertRaises(ValueError):
                self.plan(tasks)

    def test_legacy_migration_never_invents_approval(self):
        del self.state['workflow']
        guided._save(self.run, self.state, 'synthetic_legacy')
        with self.assertRaisesRegex(ValueError, 'Legacy engagement'):
            self.action('import-design', document=self.doc)
        self.action('migrate-stages')
        self.assertEqual(self.state['workflow']['approvals'], [])
        self.assertEqual(self.state['workflow']['migration'], 'legacy_adopted_without_approval')

    def test_sources_symlinks_and_credential_slices_rejected(self):
        (self.repo / 'linked.sql').symlink_to(self.repo / 'orders.sql')
        with self.assertRaises(ValueError): stages._source_hash(self.state, 'linked.sql')
        (self.repo / '.env').write_text('not a real secret')
        with self.assertRaises(ValueError): stages._source_hash(self.state, '.env')

    def test_effort_binding_and_stale_reassessment(self):
        from development_effort import FACTORS, STAGES as EFFORT_STAGES
        self.approve()
        request = {'scope': {'stages': ['implementation'], 'excluded_stages': [s for s in EFFORT_STAGES if s != 'implementation']},
                   'evidence': [{'id': 'design', 'sha256': 'a' * 64}],
                   'packages': [{'id': 'build-orders', 'stage': 'implementation', 'model_ids': ['orders'], 'depends_on': [],
                                 'material_inputs': {}, 'factors': {f: {'level': 'easy', 'rationale': 'Established bounded pattern', 'evidence_ids': ['design']} for f in FACTORS},
                                 'blockers': [], 'assumptions': []}]}
        self.action('assess-effort', document=request)
        self.assertEqual(stages.public_view(self.state)['effort']['category'], 'easy')
        request['packages'][0]['blockers'] = ['Access request pending']
        self.action('assess-effort', document=request)
        effort = stages.public_view(self.state)['effort']
        self.assertEqual(effort['category'], 'easy')
        self.assertEqual(effort['readiness'], 'blocked')
        self.assertEqual(effort['work_packages'][0]['readiness'], 'blocked')
        self.doc['revision'] += 1
        self.doc['entities'][1]['grain'] = 'One row per order line'
        self.action('import-design', document=self.doc)
        effort = stages.public_view(self.state)['effort']
        self.assertIsNone(effort['category'])
        self.assertEqual(effort['readiness'], 'needs_discovery')
        self.assertIsNone(effort['work_packages'][0]['category'])

    def test_design_change_immediately_invalidates_prepared_handoff(self):
        from test_guided_workflow import GuidedWorkflowTests
        review_path, root = GuidedWorkflowTests.handoff(self, self.state)
        review = json.loads(review_path.read_text())
        design = self.state['workflow']['design']
        review['design_binding'] = {key: design[key] for key in ('id', 'revision', 'sha256')}
        review_path.write_text(json.dumps(review))
        self.state = guided.record_handoff(self.run, review_path, root)
        self.assertEqual(self.state['status'], 'handoff_prepared')
        self.doc['revision'] += 1
        self.doc['entities'][0]['grain'] = 'One row per customer version'
        self.action('import-design', document=self.doc)
        self.assertEqual(self.state['status'], 'candidate_preparation_ready')
        self.assertNotIn('delivery', self.state)
        self.assertNotIn('review_prepared_handoff', [a['id'] for a in self.state['next_actions']])
        self.assertEqual(next(e for e in self.state['evidence'] if e['kind'] == 'prepared_handoff')['status'], 'stale')


if __name__ == '__main__':
    unittest.main()
