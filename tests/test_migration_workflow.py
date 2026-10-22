"""Refactor direction survives stage boundaries without suppressing drafts."""
import copy
import json
import unittest

import test_engagement_stages as fixtures
import migration_context
import migration_intent
import migration_artifacts
import test_agent_context as context_fixtures


def intent(domain='commerce'):
    return {'schema_version': 1, 'kind': 'migration_intent', 'domain_id': domain,
            'structural_objective': 'refactor', 'behavior': 'preserve',
            'objectives': [{'id': 'domain-model', 'statement': 'Recover shared entities from legacy transformations'}],
            'source_roles': [{'id': 'old', 'root_id': 'primary', 'role': 'legacy_baseline'}],
            'behavior_constraints': ['Retain population and currency rules; flag conflicting definitions'],
            'request_reference': 'synthetic://user/refactor'}


class MigrationWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.h = fixtures.StageTests('test_design_only_and_forged_approval_never_unlock_code')
        self.h.setUp(); self.addCleanup(self.h.doCleanups)

    def configure(self):
        self.h.action('configure-migration-intent', document=intent())

    def test_guided_contract_actions_pin_current_domain(self):
        self.configure()
        self.h.action('migration-intent-packet', document={'domain_id': 'commerce'})
        packet = self.h.state['workflow']['migration_intent_packet']
        self.assertEqual(packet['intent']['behavior'], 'preserve')
        self.assertEqual(packet['intent']['structural_objective'], 'refactor')
        self.h.action('migration-assessment-bindings', document={'domain_id': 'commerce'})
        self.assertEqual(self.h.state['workflow']['migration_assessment_request']['model_ids'], ['customers', 'orders', 'products'])
        self.assertFalse(self.h.state['readiness']['execution_authorized'])

    def test_intent_change_only_stales_affected_domain_and_dependents(self):
        doc = copy.deepcopy(self.h.doc)
        doc['entities'][2]['domain'] = 'catalog'
        doc['revision'] = 2
        self.h.action('import-design', document=doc)
        before = fixtures.stages.entity_bindings(self.h.state, ['orders', 'products'])
        self.configure()
        after = fixtures.stages.entity_bindings(self.h.state, ['orders', 'products'])
        self.assertNotEqual(before['orders'], after['orders'])
        self.assertEqual(before['products'], after['products'])
        contracts = migration_context.task_contracts(self.h.state, ['orders'])
        self.assertEqual(len(contracts), 1)
        self.assertEqual(migration_context.task_contracts(self.h.state, ['products']), [])

    def test_provisional_tasks_keep_intent_and_accept_legacy_copy_as_unqualified_candidate(self):
        self.configure()
        selected = ['customers', 'orders', 'products']
        self.h.action('request-draft', entities=selected, document={'schema_version': 1,
            'kind': 'provisional_code_request', 'requester': 'Synthetic operator',
            'request_reference': 'synthetic://request/code', 'request_text': 'Write provisional code now',
            'bindings': fixtures.stages.draft_bindings(self.h.state, selected)})
        plan = self.h.plan(self.h.tasks())
        task = next(t for t in plan['tasks'] if t['id'] == 'build-customers')
        self.assertEqual(task['generation_mode'], 'provisional')
        self.assertEqual(task['migration_intents'][0]['domain_id'], 'commerce')
        (self.h.artifacts / 'customers.sql').write_bytes((self.h.repo / 'customers.sql').read_bytes())
        self.h.action('record-task', artifact_root=self.h.artifacts, document={
            'task_id': task['id'], 'run_id': 'legacy-copy', 'plan_sha256': plan['plan_sha256'],
            'fingerprint': task['fingerprint'], 'outputs': fixtures.stages._output_hashes(self.h.artifacts, ['customers.sql']),
            'evidence_reference': 'synthetic://run/draft'})
        run = self.h.state['workflow']['runs'][-1]
        self.assertEqual(run['migration_artifact_checks'][0]['code'], 'exact_legacy_copy')
        self.assertFalse(migration_intent.summary(self.h.state)['domains'][0]['refactor_complete'])
        with self.assertRaisesRegex(ValueError, 'lacks current objective'):
            migration_intent.require_complete(self.h.state)
        with self.assertRaisesRegex(ValueError, 'retains legacy'):
            migration_artifacts.require_complete(self.h.state)
        self.assertFalse(self.h.state['readiness']['execution_authorized'])

    def test_thin_wrapper_and_raw_staging_exception_are_distinct(self):
        self.configure()
        task = self.h.tasks()['tasks'][0]
        (self.h.artifacts / 'customers.sql').write_text("select * from {{ ref('customers') }}")
        rows = migration_artifacts.inspect_task(self.h.state, task, self.h.artifacts)
        self.assertEqual(rows[0]['code'], 'possible_legacy_wrapper')
        request = intent()
        request['source_roles'].append({'id': 'staging', 'root_id': 'primary', 'role': 'raw_staging', 'path_prefix': 'customers.sql'})
        self.h.action('configure-migration-intent', document=request)
        self.assertEqual(migration_artifacts.inspect_task(self.h.state, task, self.h.artifacts), [])

    def test_subset_readiness_is_read_only_and_retains_real_integrity_failures(self):
        import design_readiness
        before = copy.deepcopy(self.h.state)
        report = design_readiness.summarize(self.h.state, ['orders'])
        self.assertEqual(report['structural']['status'], 'consistent')
        self.assertEqual(self.h.state, before)
        self.h.state['workflow']['design']['entities'][0]['grain'] = 'tampered'
        report = design_readiness.summarize(self.h.state, ['orders'])
        self.assertEqual(report['structural']['status'], 'findings')

    def test_unassessed_refactor_blocks_live_promotion_only(self):
        self.configure()
        for action, mode in [('publish_pr', 'live'), ('deploy_development', 'live'), ('promote', 'simulation')]:
            migration_artifacts.require_promotion(self.h.state, action, mode)
        with self.assertRaisesRegex(ValueError, 'lacks current objective'):
            migration_artifacts.require_promotion(self.h.state, 'promote', 'live')
        self.h.state['workflow'].pop('migration_intents')
        migration_artifacts.require_promotion(self.h.state, 'promote', 'live')

    def test_no_contract_preserves_legacy_bindings_and_completion_behavior(self):
        before = copy.deepcopy(self.h.state)
        self.assertEqual(migration_context.task_contracts(self.h.state), [])
        self.assertEqual(migration_intent.scope_bindings(self.h.state), {})
        migration_intent.require_complete(self.h.state)
        self.assertEqual(self.h.state, before)


class MigrationPacketTests(unittest.TestCase):
    def setUp(self):
        self.p = context_fixtures.AgentContextTests('test_same_input_produces_stable_packet_hash')
        self.p.setUp(); self.addCleanup(self.p.doCleanups)
        self.state = {'inputs': {'source': {'path': str(self.p.source)}}, 'workflow': {}}
        migration_intent.configure(self.state, intent())
        contracts = migration_context.task_contracts(self.state)
        self.p.request['migration_intents'] = contracts
        self.p.request['bindings'].update(migration_context.contract_bindings(contracts))

    def test_inventory_only_brief_reports_missing_evidence_without_blocking_packet(self):
        self.p.build()
        data = json.loads((self.p.root / 'packet/TASK.md').read_text().split('## Task data and selected evidence\n\n')[1])
        self.assertEqual(data['design_evidence']['domains'][0]['status'], 'context_incomplete')
        self.assertIn('legacy_transformation', data['design_evidence']['domains'][0]['missing_evidence_roles'])

    def test_exact_supplied_roles_are_qualified_not_proof_of_design_accuracy(self):
        self.p.request['design_evidence'] = [{'domain_id': 'commerce', 'evidence_id': 'source.orders', 'role': role}
                                             for role in ('legacy_transformation', 'source_contract')]
        report = migration_context.packet_evidence(self.p.request)
        self.assertEqual(report['domains'][0]['status'], 'declared_evidence_supplied')
        self.assertIn('not proof', report['qualification'])
        self.p.request['design_evidence'][0]['evidence_id'] = 'missing'
        with self.assertRaisesRegex(ValueError, 'supplied excerpts'):
            self.p.build()

    def test_omitted_and_changed_contract_cannot_keep_a_valid_pin(self):
        self.p.request['migration_intents'][0]['intent']['structural_objective'] = 'preserve'
        with self.assertRaisesRegex(ValueError, 'hash differs'):
            self.p.build()
        self.p.request.pop('migration_intents')
        with self.assertRaisesRegex(ValueError, 'complete scoped'):
            self.p.build()


if __name__ == '__main__':
    unittest.main()
