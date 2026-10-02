"""Durability, drift, interview and authority tests; no input code is executed."""
from contextlib import redirect_stdout, redirect_stderr
import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'
sys.path.insert(0, str(SCRIPTS))
import guided_workflow as workflow


def collector(repo, framework, warehouse, **options):
    """A deterministic test double for the separately tested static collector."""
    repo = Path(repo)
    content = [(str(p.relative_to(repo)), hashlib.sha256(p.read_bytes()).hexdigest())
               for p in sorted(repo.rglob('*')) if p.is_file()]
    complete = not options.get('test_incomplete', False)
    generation = 'agent_assisted' if framework and warehouse not in (None, 'gcp') else 'needs_selection'
    if framework == 'coalesce':
        generation = 'requires_contract'
    return {'schema_version': 1, 'kind': 'platform_readiness',
      'source_fingerprint': {'algorithm': 'sha256', 'value': workflow._digest(content),
                             'scope': 'bounded_nonsecret_repository', 'complete': complete},
      'selection': {'framework': framework, 'warehouse': warehouse},
      'detected_sources': [{'type': 'dbt', 'paths': ['dbt_project.yml'], 'confidence': 'static_signal'}],
      'coverage': {'complete': complete, 'scanned_files': len(content), 'gaps': []},
      'findings': [], 'questions': [],
      'capabilities': {'assessment': {'status': 'supported', 'reason': 'Read-only metadata.'},
        'generation': {'status': generation, 'reason': 'Reviewed source contract required.'},
        'execution': {'status': 'requires_operator_validation', 'reason': 'Not executed.'}}}


BASE = {'engagement_type': 'new_model', 'priority_domain': 'Order analytics',
        'framework': 'dbt', 'warehouse': 'snowflake', 'semantic_target': 'retain_existing',
        'deliverables': ['implementation', 'documentation', 'dictionary']}


class GuidedWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.repo = self.root / 'input'
        self.repo.mkdir()
        (self.repo / 'dbt_project.yml').write_text('name: source_project\nconfig-version: 2\n')
        self.run = self.root / 'engagement'
        self.catalogue = self.root / 'catalogue.json'
        self.catalogue.write_text('{"objects": [{"name": "orders"}]}\n')
        self.patcher = patch.object(workflow, '_assess_repository', collector)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def start(self, answers=None, **kwargs):
        kwargs.setdefault('catalogue', self.catalogue)
        return workflow.start_engagement(self.repo, self.run, answers, **kwargs)

    def receipt(self, name, depends_on):
        path = self.root / (name + '.json')
        path.write_text('{"claimed_status":"passed"}\n')
        state = workflow.record_evidence(self.run, path, name, depends_on)
        return next(e['id'] for e in reversed(state['evidence']) if e['kind'] == name)

    def handoff(self, state):
        import delivery_portal as portal
        root = self.root / 'candidate'
        root.mkdir(exist_ok=True)
        body = b'select 1 as order_id\n'
        (root / 'orders.sql').write_bytes(body)
        review = {'schema_version': 1, 'title': 'Synthetic handoff',
                  'source_fingerprint': portal.source_fingerprint(state),
                  'context_sha256': portal.context_fingerprint(state),
                  'target': {'framework': state['answers']['framework'], 'warehouse': state['answers']['warehouse']},
                  'models': [], 'relationships': [], 'validation': [],
                  'artifacts': [{'id': 'orders', 'path': 'orders.sql', 'category': 'implementation',
                                 'audiences': ['engineer'], 'sha256': hashlib.sha256(body).hexdigest()}]}
        path = self.root / 'review.json'
        path.write_text(json.dumps(review))
        return path, root

    def test_prepared_handoff_survives_resume_and_packages_without_approval(self):
        import delivery_portal as portal
        review, root = self.handoff(self.start(BASE))
        state = workflow.record_handoff(self.run, review, root)
        self.assertEqual(state['status'], 'handoff_prepared')
        self.assertEqual(state['delivery']['artifact_count'], 1)
        self.assertEqual(state['delivery']['assurance'], 'file_integrity_only')
        self.assertFalse(state['readiness']['execution_authorized'])
        resumed = workflow.resume_engagement(self.run)
        self.assertEqual(resumed['status'], 'handoff_prepared')
        self.assertEqual(resumed['next_actions'][0]['id'], 'review_prepared_handoff')
        package = self.root / 'handoff.zip'
        portal.package_delivery(resumed, json.loads(review.read_text()), root, package, audience='engineer')
        self.assertEqual(portal.verify_delivery(package)['status'], 'integrity_verified')

    def test_handoff_file_review_and_dependency_drift_invalidates_prepared_status(self):
        for case in ('file', 'deleted', 'review', 'source', 'catalogue', 'target', 'runtime', 'domain', 'selection', 'audience'):
            with self.subTest(case=case):
                self.run = self.root / ('run-' + case)
                review, root = self.handoff(self.start(BASE))
                workflow.record_handoff(self.run, review, root)
                answers = None
                if case == 'file': (root / 'orders.sql').write_text('select 2 as order_id')
                elif case == 'deleted': (root / 'orders.sql').unlink()
                elif case == 'review': review.write_text(review.read_text() + '\n')
                elif case == 'source': (self.repo / 'changed.sql').write_text('select 2')
                elif case == 'catalogue': self.catalogue.write_text('{"objects":[{"name":"orders","type":"TABLE"}]}')
                elif case == 'target': answers = {'warehouse': 'bigquery'}
                elif case == 'runtime': answers = {'environment': 'Different host'}
                elif case == 'domain': answers = {'priority_domain': 'Billing'}
                elif case == 'selection': answers = {'deliverables': ['documentation']}
                elif case == 'audience': answers = {'audience': 'reviewer'}
                state = workflow.update_answers(self.run, answers) if answers else workflow.resume_engagement(self.run)
                self.assertNotEqual(state['status'], 'handoff_prepared')
                self.assertNotIn('delivery', state)
                record = next(e for e in state['evidence'] if e['kind'] == 'prepared_handoff')
                self.assertEqual(record['status'], 'stale')
                self.assertTrue(record['invalidated_by'])

    def test_unverified_claim_cannot_advance_handoff(self):
        self.start(BASE)
        self.receipt('prepared_handoff', ['source'])
        state = workflow.resume_engagement(self.run)
        self.assertEqual(state['status'], 'candidate_preparation_ready')
        self.assertNotIn('delivery', state)

    def test_malformed_regenerated_svg_review_invalidates_without_crashing(self):
        review, root = self.handoff(self.start(dict(BASE, deliverables=['diagrams'])))
        content = b'<svg xmlns="http://www.w3.org/2000/svg"><rect width="10" height="10"/></svg>'
        (root / 'model.svg').write_bytes(content)
        manifest = json.loads(review.read_text())
        manifest['artifacts'] = [{'id': 'diagram', 'path': 'model.svg', 'category': 'diagrams',
                                  'audiences': ['engineer'], 'sha256': hashlib.sha256(content).hexdigest()}]
        review.write_text(json.dumps(manifest))
        workflow.record_handoff(self.run, review, root)
        broken = b'<svg><rect>'
        (root / 'model.svg').write_bytes(broken)
        manifest['artifacts'][0]['sha256'] = hashlib.sha256(broken).hexdigest()
        review.write_text(json.dumps(manifest))
        state = workflow.resume_engagement(self.run)
        self.assertEqual(state['status'], 'candidate_preparation_ready')
        self.assertNotIn('delivery', state)
        self.assertEqual(next(e for e in state['evidence'] if e['kind'] == 'prepared_handoff')['status'], 'stale')

    def test_handoff_rejects_stale_review_and_unfinished_interview(self):
        review, root = self.handoff(self.start(BASE))
        workflow.update_answers(self.run, {'warehouse': 'bigquery'})
        with self.assertRaisesRegex(ValueError, 'stale|target'):
            workflow.record_handoff(self.run, review, root)
        workflow.update_answers(self.run, {'warehouse': 'unknown'})
        with self.assertRaisesRegex(ValueError, 'prerequisites'):
            workflow.record_handoff(self.run, review, root)

    def test_repeated_handoff_supersedes_previous_record_without_losing_history(self):
        review, root = self.handoff(self.start(BASE))
        workflow.record_handoff(self.run, review, root)
        state = workflow.record_handoff(self.run, review, root)
        records = [e for e in state['evidence'] if e['kind'] == 'prepared_handoff']
        self.assertEqual([e['status'] for e in records], ['superseded', 'current'])
        self.assertEqual(workflow.resume_engagement(self.run)['status'], 'handoff_prepared')

    def test_cli_records_actual_handoff(self):
        review, root = self.handoff(self.start(BASE))
        with redirect_stdout(io.StringIO()):
            result = workflow.main(['record-handoff', '--run', str(self.run), '--review', str(review),
                                    '--artifact-root', str(root), '--no-render'])
        self.assertEqual(result, 0)
        self.assertEqual(workflow.load_engagement(self.run)['status'], 'handoff_prepared')

    def test_raw_only_discovery_to_provisional_package_uses_actual_collector(self):
        import delivery_portal as portal
        from platform_readiness import assess_repository
        raw = self.root / 'raw-only'
        raw.mkdir()
        original = b'order_id,amount\n001,12.50\n002,0.00\n'
        (raw / 'orders.csv').write_bytes(original)
        with patch.object(workflow, '_assess_repository', assess_repository):
            state = workflow.start_engagement(raw, self.run, dict(BASE, semantic_target='omni'), catalogue=self.catalogue)
            self.assertEqual(state['status'], 'candidate_preparation_ready')
            inventory = state['readiness']['platform']['raw_csv_inventory']
            self.assertEqual(inventory[0]['row_count'], 2)
            self.assertFalse(inventory[0]['native_types_verified'])
            self.assertFalse((raw / 'dbt_project.yml').exists())
            review, root = self.handoff(state)
            state = workflow.record_handoff(self.run, review, root)
            self.assertEqual(workflow.resume_engagement(self.run)['status'], 'handoff_prepared')
            package = self.root / 'raw-provisional.zip'
            portal.package_delivery(state, json.loads(review.read_text()), root, package, audience='engineer')
            self.assertEqual(portal.verify_delivery(package)['status'], 'integrity_verified')
            self.assertFalse(state['readiness']['execution_authorized'])
        self.assertEqual((raw / 'orders.csv').read_bytes(), original)

    def test_start_read_only_short_round_does_not_infer_target_from_dbt_source(self):
        original = (self.repo / 'dbt_project.yml').read_bytes()
        state = self.start()
        self.assertEqual(state['status'], 'interview_pending')
        self.assertEqual(state['answers'], {})
        self.assertIsNone(state['inputs']['target']['framework'])
        self.assertEqual(len(state['readiness']['questions']), 3)
        self.assertTrue(state['readiness']['assessment_allowed'])
        self.assertFalse(state['readiness']['generation_ready'])
        self.assertEqual(original, (self.repo / 'dbt_project.yml').read_bytes())
        self.assertEqual(state, workflow.load_engagement(self.run))

    def test_answers_resume_and_unknowns_survive_without_repeated_questions(self):
        self.start({'engagement_type': 'new_model', 'priority_domain': 'Orders'})
        updated = workflow.update_answers(self.run, {'framework': 'dbt', 'warehouse': 'unknown'})
        self.assertEqual(updated['answers']['warehouse'], 'unknown')
        resumed = workflow.resume_engagement(self.run)
        self.assertEqual(updated['answers'], resumed['answers'])
        ids = [q['id'] for q in resumed['readiness']['questions']]
        self.assertNotIn('engagement_type', ids)
        self.assertNotIn('priority_domain', ids)
        self.assertNotIn('framework', ids)
        self.assertIn('warehouse', ids)
        self.assertEqual(resumed['history'][-1]['action'], 'resumed')

    def test_gcp_requires_confirmation_and_never_silently_becomes_bigquery(self):
        answers = dict(BASE, warehouse='gcp')
        state = self.start(answers)
        self.assertEqual(state['answers']['warehouse'], 'gcp')
        self.assertFalse(state['readiness']['generation_ready'])
        self.assertEqual(state['readiness']['missing_answers'], ['warehouse'])
        self.assertIn('BigQuery', state['readiness']['questions'][0]['prompt'])
        confirmed = workflow.update_answers(self.run, {'warehouse': 'bigquery'})
        self.assertTrue(confirmed['readiness']['generation_ready'])

    def test_migration_and_refactor_need_baseline_and_explicit_behavior_choices(self):
        for mode in ('migration', 'refactor'):
            with self.subTest(mode=mode):
                run = self.root / mode
                state = workflow.start_engagement(self.repo, run, dict(BASE, engagement_type=mode), catalogue=self.catalogue)
                self.assertEqual(state['readiness']['missing_answers'], ['trusted_outputs', 'retained_behavior', 'corrected_behavior'])
                state = workflow.update_answers(run, {'trusted_outputs': ['Report 42, revision 3'], 'retained_behavior': ['Order population and timezone']})
                self.assertEqual(state['readiness']['missing_answers'], ['corrected_behavior'])
                state = workflow.update_answers(run, {'corrected_behavior': []})
                self.assertTrue(state['readiness']['generation_ready'])
                self.assertFalse(state['readiness']['execution_authorized'])

    def test_incomplete_source_coverage_cannot_report_generation_ready(self):
        state = self.start(BASE, readiness_options={'test_incomplete': True})
        self.assertTrue(state['readiness']['interview_complete'])
        self.assertFalse(state['readiness']['generation_ready'])
        self.assertEqual(state['status'], 'needs_evidence')

    def test_coalesce_requires_qualified_contract_despite_complete_interview(self):
        state = self.start(dict(BASE, framework='coalesce'))
        self.assertEqual(state['status'], 'assessment_ready')
        self.assertFalse(state['readiness']['generation_ready'])
        self.assertTrue(state['next_actions'])

    def test_source_drift_invalidates_source_bound_receipts_only(self):
        self.start(BASE)
        source_id = self.receipt('source_analysis', ['source'])
        target_id = self.receipt('target_contract', ['target'])
        before = workflow.load_engagement(self.run)
        (self.repo / 'extra.sql').write_text('select 1\n')
        state = workflow.resume_engagement(self.run)
        self.assertNotEqual(before['source_fingerprint'], state['source_fingerprint'])
        by_id = {e['id']: e for e in state['evidence']}
        self.assertEqual(by_id[source_id]['status'], 'stale')
        self.assertEqual(by_id[source_id]['invalidated_by'], ['source'])
        self.assertEqual(by_id[target_id]['status'], 'current')
        self.assertEqual(before['answers'], state['answers'])

    def test_catalogue_drift_preserves_unrelated_source_receipt_and_history(self):
        self.start(BASE, catalogue=self.catalogue)
        catalogue_id = self.receipt('catalogue_binding', ['catalogue'])
        source_id = self.receipt('source_inventory', ['source'])
        before = workflow.load_engagement(self.run)
        self.catalogue.write_text('{"objects":[{"name":"orders_v2"}]}\n')
        state = workflow.resume_engagement(self.run)
        by_id = {e['id']: e for e in state['evidence']}
        self.assertEqual(by_id[catalogue_id]['status'], 'stale')
        self.assertEqual(by_id[source_id]['status'], 'current')
        self.assertEqual(state['history'][:len(before['history'])], before['history'])

    def test_catalogue_disappearance_is_retained_as_gap_and_invalidates_binding(self):
        self.start(BASE, catalogue=self.catalogue)
        evidence_id = self.receipt('catalogue_binding', ['catalogue'])
        self.catalogue.unlink()
        state = workflow.resume_engagement(self.run)
        self.assertFalse(state['inputs']['catalogue']['available'])
        self.assertIsNone(state['inputs']['catalogue']['sha256'])
        self.assertEqual(next(e for e in state['evidence'] if e['id'] == evidence_id)['status'], 'stale')
        self.assertFalse(state['readiness']['generation_ready'])
        self.assertEqual(state['status'], 'needs_evidence')
        self.assertIn('restore_catalogue', [a['id'] for a in state['next_actions']])

    def test_absent_catalogue_allows_assessment_but_blocks_dependent_generation(self):
        state = self.start(BASE, catalogue=None)
        self.assertTrue(state['readiness']['assessment_allowed'])
        self.assertTrue(state['readiness']['interview_complete'])
        self.assertFalse(state['readiness']['generation_ready'])
        self.assertEqual(state['status'], 'needs_evidence')
        self.assertIn('capture_catalogue', [a['id'] for a in state['next_actions']])
        state = workflow.assess_engagement(self.run, catalogue=self.catalogue)
        self.assertEqual(state['status'], 'candidate_preparation_ready')
        self.assertIn('verify_catalogue', state['readiness']['qualification'])

    def test_target_and_runtime_choices_are_separate_dependencies(self):
        self.start(BASE)
        target_id = self.receipt('target_definition', ['target'])
        runtime_id = self.receipt('runtime_check', ['runtime'])
        state = workflow.update_answers(self.run, {'host': 'Codex', 'environment': 'Local review only'})
        by_id = {e['id']: e for e in state['evidence']}
        self.assertEqual(by_id[target_id]['status'], 'current')
        self.assertEqual(by_id[runtime_id]['status'], 'stale')
        state = workflow.update_answers(self.run, {'warehouse': 'databricks'})
        self.assertEqual(next(e for e in state['evidence'] if e['id'] == target_id)['status'], 'stale')
        self.assertEqual(state['inputs']['runtime']['host'], 'Codex')

    def test_domain_change_invalidates_design_without_erasing_source_assessment(self):
        self.start(BASE)
        design_id = self.receipt('model_design', ['discovery'])
        source_id = self.receipt('source_inventory', ['source'])
        state = workflow.update_answers(self.run, {'priority_domain': 'Billing'})
        by_id = {e['id']: e for e in state['evidence']}
        self.assertEqual(by_id[design_id]['status'], 'stale')
        self.assertEqual(by_id[source_id]['status'], 'current')

    def test_atomic_state_failure_keeps_previous_commit_and_can_resume(self):
        before = self.start(BASE)
        state_bytes = (self.run / 'state.json').read_bytes()
        original_replace = workflow.os.replace
        def interrupted(src, dst):
            if Path(dst).name == 'state.json':
                raise OSError('simulated interruption before atomic replace')
            return original_replace(src, dst)
        with patch.object(workflow.os, 'replace', interrupted):
            with self.assertRaisesRegex(OSError, 'simulated interruption'):
                workflow.update_answers(self.run, {'priority_domain': 'Uncommitted answer'})
        self.assertEqual((self.run / 'state.json').read_bytes(), state_bytes)
        self.assertEqual(workflow.load_engagement(self.run), before)
        self.assertFalse(any(p.name.startswith('.state.json.') for p in self.run.iterdir()))
        resumed = workflow.resume_engagement(self.run)
        self.assertEqual(resumed['answers']['priority_domain'], BASE['priority_domain'])
        self.assertGreater(resumed['revision'], before['revision'] + 1)
        self.assertEqual(json.loads((self.run / 'revisions/000001.json').read_text()), before)

    def test_resume_recovers_durable_revision_after_interrupted_initial_start(self):
        with patch.object(workflow.os, 'replace', side_effect=OSError('initial interruption')):
            with self.assertRaisesRegex(OSError, 'initial interruption'):
                self.start(BASE)
        self.assertFalse((self.run / 'state.json').exists())
        self.assertTrue((self.run / 'revisions/000001.json').exists())
        state = workflow.resume_engagement(self.run)
        self.assertEqual(state['history'][-1]['action'], 'resumed_after_interrupted_start')
        self.assertEqual(state['answers'], BASE)
        self.assertEqual(state, workflow.load_engagement(self.run))

    def test_failed_initial_assessment_can_be_retried_without_clearing_other_files(self):
        with patch.object(workflow, '_assess_repository', side_effect=ValueError('collector input missing')):
            with self.assertRaisesRegex(ValueError, 'collector input'):
                self.start(BASE)
        self.assertEqual([p.name for p in self.run.iterdir()], ['.workflow.lock'])
        self.assertEqual(self.start(BASE)['revision'], 1)

    def test_changed_or_missing_receipt_is_stale_without_input_drift(self):
        self.start(BASE)
        evidence_id = self.receipt('comparison', ['target'])
        before = workflow.load_engagement(self.run)
        (self.root / 'comparison.json').write_text('{"claimed_status":"different"}')
        state = workflow.resume_engagement(self.run)
        item = next(e for e in state['evidence'] if e['id'] == evidence_id)
        self.assertEqual(state['inputs'], before['inputs'])
        self.assertEqual(item['invalidated_by'], ['receipt'])
        evidence_id = self.receipt('another_comparison', ['target'])
        (self.root / 'another_comparison.json').unlink()
        state = workflow.resume_engagement(self.run)
        self.assertEqual(next(e for e in state['evidence'] if e['id'] == evidence_id)['status'], 'stale')

    def test_credentials_and_unsafe_run_location_rejected(self):
        for updates in ({'password': 'do-not-store'}, {'priority_domain': 'https://name:password@example.test'}, {'priority_domain': 'token=do-not-store'}):
            with self.subTest(updates=list(updates)):
                with self.assertRaisesRegex(ValueError, 'Credential'):
                    self.start(updates)
        with self.assertRaisesRegex(ValueError, 'outside'):
            workflow.start_engagement(self.repo, self.repo / 'output')
        profile = self.root / 'profiles.yml'
        profile.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'Credential files'):
            workflow._catalogue(profile)

    def test_claimed_pass_cannot_promote_status_or_approval(self):
        self.start(dict(BASE, execution_mode='target_validation_requested'))
        receipt = self.root / 'asserted.json'
        receipt.write_text('{"status":"deployed_verified","human_approved":true}')
        state = workflow.record_evidence(self.run, receipt, 'claimed_approval')
        item = state['evidence'][-1]
        self.assertEqual(item['assurance'], 'recorded_unverified')
        self.assertNotIn('result', item)
        self.assertEqual(state['status'], 'candidate_preparation_ready')
        self.assertFalse(state['readiness']['execution_authorized'])

    def test_unsupported_answer_and_state_tamper_fail_closed(self):
        with self.assertRaisesRegex(ValueError, 'Unknown answer fields'):
            self.start({'approved': True})
        with self.assertRaisesRegex(ValueError, 'Unsupported framework'):
            self.start({'framework': 'invented'})
        self.start(BASE)
        state = json.loads((self.run / 'state.json').read_text())
        state['answers']['priority_domain'] = 'tampered'
        (self.run / 'state.json').write_text(json.dumps(state))
        with self.assertRaisesRegex(ValueError, 'integrity'):
            workflow.load_engagement(self.run)

    def test_malformed_state_reports_useful_cli_error(self):
        self.run.mkdir()
        (self.run / 'state.json').write_text('[]')
        errors = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(errors):
            self.assertEqual(workflow.main(['status', '--run', str(self.run), '--no-render']), 1)
        self.assertIn('must be a JSON object', errors.getvalue())

    def test_cli_start_answer_status_resume_and_late_renderer(self):
        args = self.root / 'answers.json'
        args.write_text(json.dumps(BASE))
        renderer = types.ModuleType('delivery_portal')
        calls = []
        renderer.render_engagement = lambda state, output: calls.append((state['engagement_id'], output))
        with patch.dict(sys.modules, {'delivery_portal': renderer}), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(workflow.main(['init', '--repo', str(self.repo), '--run', str(self.run), '--answers', str(args)]), 0)
            self.assertEqual(workflow.main(['answer', '--run', str(self.run), '--set', 'priority_domain=Invoices']), 0)
            self.assertEqual(workflow.main(['status', '--run', str(self.run)]), 0)
            self.assertEqual(workflow.main(['resume', '--run', str(self.run)]), 0)
        self.assertEqual(len(calls), 4)
        self.assertTrue(all(output == self.run / 'START_HERE.html' for _, output in calls))
        self.assertEqual(workflow.load_engagement(self.run)['answers']['priority_domain'], 'Invoices')

    def test_all_warehouse_choices_and_unsupported_pairings_use_real_collector(self):
        from platform_readiness import assess_repository
        with patch.object(workflow, '_assess_repository', assess_repository):
            state = self.start(dict(BASE, framework='native_sql'))
            initial = state['source_fingerprint']
            for warehouse in workflow.WAREHOUSES:
                state = workflow.update_answers(self.run, {'warehouse': warehouse})
                self.assertEqual(state['status'], 'candidate_preparation_ready')
                self.assertEqual(state['source_fingerprint'], initial)
                self.assertEqual(state['inputs']['target']['warehouse'], warehouse)
                self.assertFalse(state['readiness']['execution_authorized'])
            state = workflow.update_answers(self.run, {'framework': 'coalesce', 'warehouse': 'redshift'})
            self.assertEqual(state['status'], 'needs_evidence')
            self.assertFalse(state['readiness']['generation_ready'])
            self.assertIn('platform.unsupported_pairing', {a['id'] for a in state['next_actions']})

    def test_real_collector_preserves_independent_target_selection_and_never_executes_input(self):
        from platform_readiness import assess_repository
        sentinel = self.root / 'must_not_exist'
        (self.repo / 'unsafe.py').write_text('from pathlib import Path\nPath(' + repr(str(sentinel)) + ').write_text("executed")\n')
        (self.repo / '.env').write_text('password=ignored-secret-marker')
        before = {p.name: p.read_bytes() for p in self.repo.iterdir()}
        with patch.object(workflow, '_assess_repository', assess_repository):
            state = self.start(BASE)
            self.assertEqual(state['inputs']['target']['warehouse'], 'snowflake')
            self.assertEqual(state['status'], 'candidate_preparation_ready')
            first = state['source_fingerprint']
            changed = workflow.update_answers(self.run, {'framework': 'native_sql', 'warehouse': 'bigquery'})
            self.assertEqual(changed['source_fingerprint'], first)
            self.assertEqual(changed['status'], 'candidate_preparation_ready')
            (self.repo / '.env').write_text('password=another-ignored-marker')
            resumed = workflow.resume_engagement(self.run)
            self.assertEqual(resumed['source_fingerprint'], first)
            self.assertNotIn('ignored-secret-marker', (self.run / 'state.json').read_text())
        self.assertFalse(sentinel.exists())
        for name, data in before.items():
            if name != '.env':
                self.assertEqual((self.repo / name).read_bytes(), data)

    def test_execution_scoped_blocker_does_not_claim_execution_or_block_preparation(self):
        def execution_only(*args, **kwargs):
            result = collector(*args, **kwargs)
            result['findings'] = [{'id': 'unsafe_hook', 'severity': 'blocker', 'summary': 'Needs host qualification',
                                  'blocks': ['execution'], 'next_action': 'Review hook on qualified host.'}]
            return result
        with patch.object(workflow, '_assess_repository', execution_only):
            state = self.start(BASE)
        self.assertTrue(state['readiness']['generation_ready'])
        self.assertFalse(state['readiness']['execution_authorized'])

    def test_parallel_writer_fails_without_overwriting_committed_state(self):
        before = self.start(BASE)
        with workflow._lock(self.run):
            with self.assertRaisesRegex(ValueError, 'Another workflow writer'):
                workflow.update_answers(self.run, {'priority_domain': 'Concurrent change'})
        self.assertEqual(workflow.load_engagement(self.run), before)

    def test_repeated_large_assessments_add_only_compact_history_with_full_revision_results(self):
        assessment_number = [0]
        def large_collector(*args, **kwargs):
            result = collector(*args, **kwargs)
            result['coverage']['exclusions'] = [
                {'path': 'generated/%04d.sql' % i, 'reason': 'static inventory detail ' + ('x' * 480)}
                for i in range(2048)]
            result['findings'] = [{'id': 'assessment_note', 'severity': 'info',
                                   'summary': 'Assessment event %d' % assessment_number[0]}]
            assessment_number[0] += 1
            return result
        with patch.object(workflow, '_assess_repository', large_collector):
            initial = self.start(BASE)
            initial_bytes = (self.run / 'state.json').read_bytes()
            initial_revision = (self.run / 'revisions/000001.json').read_bytes()
            self.assertGreater(len(initial_bytes), 1_000_000)
            previous_size = len(initial_bytes)
            for _ in range(6):
                state = workflow.resume_engagement(self.run)
                size = (self.run / 'state.json').stat().st_size
                self.assertGreater(size, previous_size)
                self.assertLess(size - previous_size, 2500)
                previous_size = size
            self.assertLess(previous_size - len(initial_bytes), 6 * 2500)
            self.assertEqual((self.run / 'revisions/000001.json').read_bytes(), initial_revision)
            assessments = [e for e in state['evidence'] if e['kind'] == 'static_readiness']
            self.assertEqual(len(assessments), 7)
            for evidence in assessments:
                self.assertNotIn('result', evidence)
                self.assertLess(len(workflow._bytes(evidence)), 1800)
                self.assertEqual(evidence['summary']['coverage']['exclusion_count'], 2048)
                self.assertEqual(evidence['result_ref']['json_pointer'], '/readiness/platform')
                revision = json.loads((self.run / evidence['result_ref']['path']).read_bytes())
                full_result = revision['readiness']['platform']
                self.assertEqual(workflow._digest(full_result), evidence['result_sha256'])
                self.assertEqual(len(full_result['coverage']['exclusions']), 2048)
            first_result = json.loads(initial_revision)['readiness']['platform']
            self.assertEqual(first_result, initial['readiness']['platform'])
            self.assertNotEqual(first_result['findings'], state['readiness']['platform']['findings'])

    def test_legacy_full_assessment_evidence_is_preserved_on_resume(self):
        initial = self.start(BASE)
        legacy = initial['evidence'][0]
        legacy['result'] = copy.deepcopy(initial['readiness']['platform'])
        legacy.pop('result_ref')
        legacy.pop('summary')
        workflow._save(self.run, initial, 'legacy_fixture')
        legacy_copy = copy.deepcopy(legacy)
        state = workflow.resume_engagement(self.run)
        self.assertEqual(state['evidence'][0], legacy_copy)
        self.assertEqual(workflow.load_engagement(self.run), state)
        self.assertNotIn('result', state['evidence'][-1])
        self.assertIn('result_ref', state['evidence'][-1])

    def test_cli_rejects_credential_file_before_read_and_accepts_bounded_scan_options(self):
        options = self.root / 'readiness-options.json'
        options.write_text('{"test_incomplete":true}')
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(workflow.main(['start', '--repo', str(self.repo), '--run', str(self.run),
                '--no-render', '--readiness-options', str(options)]), 0)
        self.assertEqual(workflow.load_engagement(self.run)['readiness_options'], {'test_incomplete': True})
        args = types.SimpleNamespace(answers=self.root / 'profiles.yml', set=[])
        with patch.object(workflow, '_json_with_hash', side_effect=AssertionError('Must not read credential file')):
            with self.assertRaisesRegex(ValueError, 'Credential files'):
                workflow._cli_answers(args)


if __name__ == '__main__':
    unittest.main()
