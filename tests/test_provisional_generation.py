"""Explicit draft requests allow files, never fabricate physical evidence or approval."""
import copy
from contextlib import redirect_stdout
import io
import json
import unittest

import test_engagement_stages as fixtures

stages = fixtures.stages
guided = fixtures.guided


class ProvisionalGenerationTests(unittest.TestCase):
    def setUp(self):
        self.h = fixtures.StageTests('test_design_only_and_forged_approval_never_unlock_code')
        self.h.setUp(); self.addCleanup(self.h.doCleanups)
        self.scope = ['customers', 'orders', 'products']
        self.h.state = guided.assess_engagement(self.h.run, catalogue=None)

    def request(self):
        return {'schema_version': 1, 'kind': 'provisional_code_request',
                'requester': 'Synthetic operator', 'request_reference': 'synthetic://conversation/draft',
                'request_text': 'Generate provisional dbt and Omni code from the available source. Catalogue is pending.',
                'bindings': stages.draft_bindings(self.h.state, self.scope)}

    def request_draft(self):
        self.h.action('request-draft', entities=self.scope, document=self.request())

    def tasks(self):
        result = self.h.tasks()
        result['tasks'][-1].update(entity_ids=self.scope, depends_on=['build-' + n for n in self.scope])
        return result

    def finish_code(self):
        self.h.plan(self.tasks())
        for task in ('build-customers', 'build-orders', 'build-products', 'semantic'):
            self.h.complete(task)

    def test_missing_catalogue_without_explicit_request_still_blocks_generation(self):
        with self.assertRaisesRegex(ValueError, 'physical prerequisites'):
            self.h.action('stage', entities=self.scope, stage='implementation')
        self.assertFalse(self.h.state['readiness']['generation_ready'])
        self.assertTrue(self.h.state['readiness']['provisional_generation_available'])
        self.assertFalse(stages.draft_entities(self.h.state))

    def test_request_opens_only_draft_generation_without_inventing_catalogue_or_approval(self):
        self.request_draft()
        self.h.action('stage', entities=self.scope, stage='implementation')
        self.assertFalse(self.h.state['readiness']['generation_ready'])
        self.assertFalse(self.h.state['readiness']['execution_authorized'])
        self.assertIsNone(self.h.state['inputs']['catalogue'])
        self.assertEqual(stages.approved_entities(self.h.state), set())
        plan = self.h.plan(self.tasks())
        self.assertEqual(plan['tasks'][0]['generation_mode'], 'provisional')
        self.assertEqual(next(t for t in plan['tasks'] if t['stage'] == 'semantic')['action'], 'blocked')

    def test_recorded_drafts_allow_semantic_files_but_not_validation_or_deployment(self):
        self.request_draft(); self.finish_code()
        self.h.action('stage', entities=self.scope, stage='semantic')
        view = stages.public_view(self.h.state)
        self.assertEqual(view['delivery_status'], 'provisional_code_generated')
        self.assertEqual(view['current_stage'], 'validation')
        for stage in ('implementation', 'semantic'):
            self.assertEqual(next(row['status'] for row in view['stages'] if row['id'] == stage), 'provisional_outputs_recorded')
        self.assertTrue(all(run['generation_mode'] == 'provisional' for run in self.h.state['workflow']['runs']))
        for stage in ('validation', 'deployment'):
            with self.subTest(stage=stage), self.assertRaises(ValueError):
                self.h.action('stage', entities=self.scope, stage=stage)
        self.assertEqual(stages.approved_entities(self.h.state), set())

    def test_unknown_policies_remain_unresolved_in_draft(self):
        self.h.doc['revision'] += 1
        self.h.doc['entities'][0].update(history='unknown', security='unknown')
        self.h.action('import-design', document=self.h.doc)
        self.request_draft()
        self.h.action('stage', entities=self.scope, stage='implementation')
        self.assertTrue(stages._design_gaps(self.h.state, self.scope))
        self.assertFalse(stages.approved_entities(self.h.state))

    def test_unknown_business_answers_allow_explicit_drafts_without_becoming_known(self):
        unknown = {'trusted_outputs': None, 'retained_behavior': None, 'corrected_behavior': None}
        self.h.state = guided.update_answers(self.h.run, {**unknown, 'engagement_type': 'refactor'})
        self.assertTrue(set(unknown) <= set(self.h.state['readiness']['missing_answers']))
        self.assertFalse(self.h.state['readiness']['interview_complete'])
        self.request_draft()
        self.h.action('stage', entities=self.scope, stage='implementation')
        self.assertTrue(all(self.h.state['answers'][key] is None for key in unknown))
        self.assertFalse(stages.approved_entities(self.h.state))
        for stage in ('validation', 'deployment'):
            with self.subTest(stage=stage), self.assertRaises(ValueError):
                self.h.action('stage', entities=self.scope, stage=stage)

    def test_unknown_target_or_disclosure_choices_still_block_drafts(self):
        for field in ('warehouse', 'framework', 'input_handling', 'migration_scope'):
            with self.subTest(field=field):
                original = self.h.state['answers'][field]
                self.h.state = guided.update_answers(self.h.run, {field: None})
                with self.assertRaisesRegex(ValueError, 'Resolve discovery'):
                    self.request_draft()
                self.h.state = guided.update_answers(self.h.run, {field: original})

    def test_partial_drafts_keep_their_provisional_label(self):
        self.request_draft()
        self.h.plan({'schema_version': 1, 'tasks': self.tasks()['tasks'][:1]})
        self.h.complete('build-customers')
        view = stages.public_view(self.h.state)
        row = next(row for row in view['stages'] if row['id'] == 'implementation')
        self.assertEqual(row['status'], 'partial_provisional_outputs')
        self.assertIn('provisional', view['next_action'])
        self.assertEqual(view['delivery_status'], 'requested_outputs_pending')

    def test_stale_request_or_wrong_operation_is_rejected(self):
        request = self.request()
        request['bindings']['operation'] = 'design_review'
        with self.assertRaisesRegex(ValueError, 'stale'): self.h.action('request-draft', entities=self.scope, document=request)
        request = self.request()
        self.h.doc['revision'] += 1
        self.h.doc['entities'][0]['grain'] = 'One row per account'
        self.h.action('import-design', document=self.h.doc)
        with self.assertRaisesRegex(ValueError, 'stale'): self.h.action('request-draft', entities=self.scope, document=request)

    def test_source_change_invalidates_request_and_draft_outputs(self):
        self.request_draft(); self.finish_code()
        (self.h.repo / 'orders.sql').write_text('select 2 as orders_id')
        self.h.state = guided.resume_engagement(self.h.run)
        self.assertNotIn('orders', stages.draft_entities(self.h.state))
        self.assertEqual(next(t['action'] for t in self.h.plan()['tasks'] if t['id'] == 'build-orders'), 'blocked')

    def test_catalogue_arrival_does_not_silently_promote_drafts(self):
        self.request_draft(); self.finish_code()
        self.h.state = guided.assess_engagement(self.h.run, catalogue=self.h.catalogue)
        self.assertFalse(stages.draft_entities(self.h.state))
        self.assertFalse(stages.approved_entities(self.h.state))
        self.assertTrue(all(task['action'] == 'blocked' for task in self.h.plan()['tasks']))
        self.h.action('approve-design', entities=self.scope, document={
            'schema_version': 1, 'kind': 'human_design_review', 'decision': 'approve',
            'reviewer': 'Synthetic reviewer', 'review_reference': 'synthetic://review/reconcile',
            'bindings': stages.review_bindings(self.h.state, self.scope)})
        plan = self.h.plan()
        self.assertFalse(any(task['action'] == 'reuse' for task in plan['tasks']))
        self.assertEqual(plan['tasks'][0]['generation_mode'], 'reviewed_candidate')

    def test_scope_cannot_expand_from_a_smaller_draft_request(self):
        self.scope = ['customers']; self.request_draft()
        self.h.action('stage', entities=['customers'], stage='implementation')
        with self.assertRaises(ValueError): self.h.action('stage', entities=['products'], stage='implementation')

    def test_incomplete_source_scan_or_other_platform_blockers_cannot_be_waived(self):
        self.h.state = guided.assess_engagement(self.h.run, readiness_options={'test_incomplete': True})
        with self.assertRaisesRegex(ValueError, 'source coverage'): self.request_draft()

    def test_draft_gate_is_shared_across_warehouse_targets_and_target_drift_invalidates_it(self):
        for warehouse in ('snowflake', 'databricks', 'bigquery', 'redshift', 'clickhouse', 'motherduck'):
            with self.subTest(warehouse=warehouse):
                self.h.state = guided.update_answers(self.h.run, {'warehouse': warehouse})
                self.assertFalse(stages.draft_entities(self.h.state))
                self.request_draft()
                self.h.action('stage', entities=self.scope, stage='implementation')
                self.assertEqual(stages.draft_entities(self.h.state), set(self.scope))
                self.assertFalse(self.h.state['readiness']['execution_authorized'])

    def test_native_artifact_rules_preserve_coalesce_and_explicit_existing_model_reuse(self):
        state = copy.deepcopy(self.h.state)
        task = self.tasks()['tasks'][0]
        task['outputs'] = ['binding.json']
        with self.assertRaisesRegex(ValueError, 'native code artifacts'):
            stages._code_artifacts(state, task)
        task['outputs'] = ['sources.yml']
        self.assertEqual(stages._code_artifacts(state, task), ['sources.yml'])
        task['outputs'] = ['binding.json']
        state['workflow']['design']['entities'][0]['disposition'] = 'reuse'
        self.assertEqual(stages._code_artifacts(state, task), ['binding.json'])
        state['workflow']['design']['entities'][0]['disposition'] = 'create'
        state['answers']['framework'] = 'coalesce'
        task['outputs'] = ['node.yml']
        self.assertEqual(stages._code_artifacts(state, task), ['node.yml'])

    def test_omni_native_filenames_are_valid_code_artifacts(self):
        self.request_draft()
        for name in ('orders.view', 'orders.query.view', 'orders.topic', 'model',
                     'relationships', 'orders.view.yaml', 'orders.topic.yml'):
            with self.subTest(name=name):
                tasks = self.tasks()
                task = tasks['tasks'][-1]
                task['outputs'] = ['omni/' + name]
                self.assertEqual(stages._code_artifacts(self.h.state, task), task['outputs'])
                self.h.plan(tasks)

    def test_tampered_retained_request_is_not_valid(self):
        self.request_draft()
        state = copy.deepcopy(self.h.state)
        state['workflow']['draft_requests'][0]['request']['request_text'] = 'Changed request'
        self.assertFalse(stages.draft_entities(state))

    def test_cli_records_request_and_renders_provisional_progress(self):
        base = ['--run', str(self.h.run), '--entities'] + self.scope
        with redirect_stdout(io.StringIO()):
            self.assertEqual(guided.main(['draft-bindings'] + base + ['--no-render']), 0)
        self.h.state = guided.load_engagement(self.h.run)
        request = self.request()
        request['bindings'] = self.h.state['workflow']['draft_request_bindings']
        path = self.h.root / 'request.json'
        path.write_text(json.dumps(request))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(guided.main(['request-draft'] + base + ['--document', str(path)]), 0)
            self.assertEqual(guided.main(['stage'] + base + ['--stage', 'implementation', '--no-render']), 0)
        self.h.state = guided.load_engagement(self.h.run)
        self.assertEqual(stages.draft_entities(self.h.state), set(self.scope))
        self.assertFalse(stages.approved_entities(self.h.state))
        self.assertTrue((self.h.run / 'START_HERE.html').is_file())
        view = stages.public_view(self.h.state)
        self.assertEqual(view['current_stage'], 'implementation')
        self.assertIn('provisional files', view['next_action'])

    def test_empty_code_file_cannot_be_registered_as_generated(self):
        self.request_draft()
        plan = self.h.plan(self.tasks())
        task = next(t for t in plan['tasks'] if t['id'] == 'build-customers')
        (self.h.artifacts / 'customers.sql').write_text('  \n')
        with self.assertRaisesRegex(ValueError, 'artifact is empty'):
            self.h.action('record-task', artifact_root=self.h.artifacts, document={
                'task_id': task['id'], 'run_id': 'empty-code', 'plan_sha256': plan['plan_sha256'],
                'fingerprint': task['fingerprint'],
                'outputs': stages._output_hashes(self.h.artifacts, ['customers.sql']),
                'evidence_reference': 'synthetic://empty-code'})


if __name__ == '__main__': unittest.main()
