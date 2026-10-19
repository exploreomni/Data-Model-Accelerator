"""Cross-component synthetic acceptance; no native warehouse or agent execution."""
import copy
import hashlib
import json
from pathlib import Path
import re
import shutil
import importlib.util
import unittest
import zipfile

import test_engagement_stages as fixtures
import delivery_portal as portal
import finalize_delivery as finalizer
from design_consistency import project_review
from disclosure_fixtures import synthetic_disclosure

stages, guided = fixtures.stages, fixtures.guided


class ReliableJourneyTests(unittest.TestCase):
    def setUp(self):
        self.h = fixtures.StageTests('test_design_only_and_forged_approval_never_unlock_code')
        self.h.setUp(); self.addCleanup(self.h.doCleanups)
        self.h.state = guided.update_answers(self.h.run, {'deliverables': ['documentation', 'dictionary', 'diagrams'],
                                                       'audience': 'engineer'})

    def review(self):
        body = '# Proposed model\n\nSynthetic design. Native and business verification remain pending.\n'
        (self.h.artifacts / 'model.md').write_text(body)
        result = {'schema_version': 1, 'title': 'Synthetic coherent model',
                  'description': 'Proposed design; native execution not performed.',
                  'source_fingerprint': portal.source_fingerprint(self.h.state),
                  'context_sha256': portal.context_fingerprint(self.h.state),
                  'target': {'framework': 'dbt', 'warehouse': 'snowflake'},
                  'artifacts': [{'id': 'design-narrative', 'path': 'model.md', 'category': 'documentation',
                      'audiences': ['engineer', 'reviewer'], 'sha256': hashlib.sha256(body.encode()).hexdigest()}],
                  'handoff': {'design_artifact_id': 'design-narrative'}}
        projection = project_review(self.h.state['workflow']['design'])
        result.update({k: projection[k] for k in ('design_binding', 'models', 'relationships', 'assets')})
        result['disclosure'] = synthetic_disclosure(['design-narrative'], 'engineer')
        return result

    @unittest.skipUnless(shutil.which('node'), 'Node is required for offline script checks')
    def test_design_only_final_has_every_model_and_no_unrequested_code(self):
        result = finalizer.finalize_delivery(self.h.state, self.review(), self.h.artifacts, self.h.root / 'delivery', javascript=True)
        with zipfile.ZipFile(result['zip']) as archive:
            source = json.loads(archive.read('01_Model/ERD/model-source.json'))
            self.assertEqual({m['id'] for m in source['models']}, {'customers', 'orders', 'products'})
            self.assertFalse(any(n.startswith('02_Implementation/') for n in archive.namelist()))
            self.assertIn('01_Model/Dictionary/data-dictionary.csv', archive.namelist())
        self.assertFalse(self.h.state['readiness']['execution_authorized'])

    def test_matching_declared_hash_cannot_hide_column_rename(self):
        review = self.review()
        review['models'][0]['columns'][0]['name'] = 'different_key'
        with self.assertRaisesRegex(ValueError, 'canonical design'):
            finalizer.finalize_delivery(self.h.state, review, self.h.artifacts, self.h.root / 'bad-final')
        checkpoint = finalizer.finalize_delivery(self.h.state, review, self.h.artifacts,
            self.h.root / 'checkpoint', checkpoint=True)
        page = Path(checkpoint['entrypoint']).read_text()
        data = json.loads(re.search(r'<script id="delivery-data" type="application/json">(.*?)</script>', page, re.S)[1])
        self.assertEqual(data['workflow']['design_checks']['status'], 'findings')
        self.assertEqual(data['checkpoint']['status'], 'incomplete')

    def test_new_review_evidence_invalidates_old_prepared_handoff_without_deleting_files(self):
        from source_adapters.base import Report
        review = self.review()
        path = self.h.root / 'review.json'
        path.write_text(json.dumps(review))
        self.h.state = guided.record_handoff(self.h.run, path, self.h.artifacts)
        retained = (self.h.artifacts / 'model.md').read_bytes()
        report = Report('dbt', {'orders.sql': (self.h.repo / 'orders.sql').read_text()})
        report.object('orders.sql', '$', 'model', 'orders')
        report.cover('orders.sql')
        report = report.finish()
        self.h.action('record-coverage', document={'schema_version': 1, 'reports': [report],
            'expected_files': [{'source': 'dbt', 'path': 'orders.sql', 'sha256': report['source_files'][0]['sha256']}],
            'requirements': [], 'targets': [], 'mappings': []})
        receipt = next(e for e in self.h.state['evidence'] if e['kind'] == 'prepared_handoff')
        self.assertEqual(receipt['status'], 'stale')
        self.assertEqual((self.h.artifacts / 'model.md').read_bytes(), retained)
        self.assertFalse(self.h.state['readiness']['execution_authorized'])

    def test_large_shared_domain_inventory_is_partitioned_without_losing_tables(self):
        design = copy.deepcopy(self.h.doc)
        design['revision'] += 1
        template = design['entities'][0]
        for number in range(117):
            entity = copy.deepcopy(template)
            entity.update(id='entity_' + str(number), name='entity_' + str(number),
                          domain='domain_' + str(number % 4), depends_on=['customers'])
            design['entities'].append(entity)
        self.h.action('import-design', document=design)
        result = finalizer.finalize_delivery(self.h.state, self.review(), self.h.artifacts, self.h.root / 'large')
        with zipfile.ZipFile(result['zip']) as archive:
            source = json.loads(archive.read('01_Model/ERD/model-source.json'))
            self.assertEqual(len(source['models']), 120)
            pages = [n for n in archive.namelist() if n.endswith('.svg')]
            self.assertGreater(len(pages), 1)
            visible = set()
            for page in pages:
                visible.update(re.findall(r'data-model-id="([^"]+)"', archive.read(page).decode()))
            self.assertEqual(visible, {m['id'] for m in source['models']})

    @unittest.skipUnless(importlib.util.find_spec('yaml'), 'Optional YAML parser unavailable')
    def test_provisional_dispatch_resume_retains_generation_and_syntax_failure(self):
        self.h.state = guided.update_answers(self.h.run, {'deliverables': ['implementation', 'documentation', 'dictionary']}, catalogue=None)
        scope = ['customers']
        self.h.action('request-draft', entities=scope, document={'schema_version': 1, 'kind': 'provisional_code_request',
            'requester': 'Synthetic operator', 'request_reference': 'synthetic://user/request',
            'request_text': 'Generate provisional code with the missing catalogue disclosed.',
            'bindings': stages.draft_bindings(self.h.state, scope)})
        task = {'id': 'build-customers', 'stage': 'implementation', 'entity_ids': scope,
                'depends_on': [], 'components': [], 'outputs': ['customers.sql', 'schema.yml']}
        self.h.plan({'schema_version': 1, 'tasks': [task]})
        self.h.action('claim-work', document={'schema_version': 1, 'work_id': 'customers', 'attempt_id': 'customers-1',
            'role': 'analytics_engineer', 'scope_ids': scope, 'source_paths': [], 'task_id': 'build-customers'})
        self.h.action('checkpoint-work', artifact_root=self.h.artifacts, document={'schema_version': 1,
            'attempt_id': 'customers-1', 'status': 'interrupted', 'reason': 'Synthetic interruption', 'outputs': []})
        self.h.state = guided.resume_engagement(self.h.run)
        self.h.action('claim-work', document={'schema_version': 1, 'work_id': 'customers', 'attempt_id': 'customers-2',
            'role': 'analytics_engineer', 'scope_ids': scope, 'source_paths': [], 'task_id': 'build-customers'})
        (self.h.artifacts / 'customers.sql').write_text('select customers_id from customers')
        (self.h.artifacts / 'schema.yml').write_text('owners: [@team-data]\n')
        plan = self.h.plan(); work = plan['tasks'][0]
        self.h.action('record-task', artifact_root=self.h.artifacts, document={'task_id': 'build-customers',
            'run_id': 'candidate-1', 'plan_sha256': plan['plan_sha256'], 'fingerprint': work['fingerprint'],
            'outputs': stages._output_hashes(self.h.artifacts, task['outputs']), 'evidence_reference': 'synthetic://host/run'})
        self.h.action('checkpoint-work', artifact_root=self.h.artifacts, document={'schema_version': 1,
            'attempt_id': 'customers-2', 'status': 'outputs_recorded', 'reason': 'Candidate retained', 'outputs': task['outputs']})
        view = stages.public_view(self.h.state)
        self.assertEqual(view['artifact_checks'][0]['status'], 'failed')
        self.assertEqual(self.h.state['workflow']['runs'][0]['generation_mode'], 'provisional')
        self.assertFalse(stages.approved_entities(self.h.state))
        self.h.action('claim-work', document={'schema_version': 1, 'work_id': 'customers', 'attempt_id': 'customers-3',
            'role': 'analytics_engineer', 'scope_ids': scope, 'source_paths': [], 'task_id': 'build-customers'})
        self.assertEqual(self.h.state['last_work_action']['action'], 'reuse')
        self.assertEqual(len(self.h.state['workflow']['runs']), 1)
        self.assertTrue((self.h.artifacts / 'schema.yml').is_file())
