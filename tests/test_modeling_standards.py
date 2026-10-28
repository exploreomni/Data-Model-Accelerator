"""Optional standards remain scoped proposals and preserve governed identities."""
import copy
import hashlib
import unittest
from test_authoring_evidence import contract  # establishes scripts import path
import modeling_standards as standards
import naming_governance
from ae_common import hash_json


def config(version='1'):
    return {'schema_version': 1, 'version': version, 'request_reference': 'synthetic://user/standards',
        'rules': [{'id': 'sales-labels', 'entity_ids': [], 'domains': ['sales'], 'label_style': 'title_words',
                  'required_tags': ['sales'], 'description_required': True, 'sample_queries_min': 1}]}


class ModelingStandardsTests(unittest.TestCase):
    def setUp(self):
        self.state = {'workflow': {'design': {'entities': [
            {'id': 'orders', 'name': 'fct_orders', 'domain': 'sales'},
            {'id': 'products', 'name': 'dim_products', 'domain': 'catalog'}]}, 'approvals': [{'unchanged': True}]}}
        self.resources = {'schema_version': 1, 'resources': [
            {'id': 'orders', 'name': 'fct_orders', 'domain': 'sales', 'label': None, 'tags': [], 'description': None, 'sample_query_count': 0},
            {'id': 'products', 'name': 'dim_products', 'domain': 'catalog', 'label': 'Products', 'tags': [], 'description': None, 'sample_query_count': 0}]}

    def test_preview_preserves_names_approvals_and_shows_requirements(self):
        before = copy.deepcopy(self.state['workflow']['design'])
        standards.configure(self.state, config()); result = standards.preview(self.state, self.resources)
        self.assertEqual(self.state['workflow']['design'], before)
        self.assertEqual(self.state['workflow']['approvals'], [{'unchanged': True}])
        self.assertFalse(result['changes_applied'])
        self.assertEqual(result['resources'][0]['proposed_label'], 'Fct Orders')
        self.assertEqual(len(result['resources'][0]['findings']), 4)
        self.assertEqual(result['resources'][1]['status'], 'out_of_scope')
        self.assertEqual([r['id'] for r in standards.summary(self.state, ['products'])['resources']], ['products'])

    def test_revision_rechecks_only_affected_scope_and_never_changes_custom_policy(self):
        naming_governance.configure(self.state, {'schema_version': 1,
            'policy': {'schema_version': 1, 'profile': 'custom', 'platform': 'snowflake',
                       'templates': {'fact': '{business_stem}_fact'}},
            'decision_reference': 'synthetic://user/custom-convention'})
        naming_before = copy.deepcopy(naming_governance.access(self.state))
        standards.configure(self.state, config()); standards.preview(self.state, self.resources)
        old_pins = standards.scope_bindings(self.state)
        old_packet = standards.packet(self.state, ['orders'])
        new = config('2'); new['rules'].append({**new['rules'][0], 'id': 'catalog-labels', 'domains': ['catalog']})
        standards.configure(self.state, new)
        result = standards.preview(self.state, self.resources)
        self.assertEqual(result['resources'][0]['action'], 'reuse')
        self.assertEqual(old_pins['orders'], standards.scope_bindings(self.state)['orders'])
        self.assertEqual(old_packet, standards.packet(self.state, ['orders']))
        self.assertEqual(result['resources'][1]['action'], 'review')
        self.assertEqual(naming_governance.access(self.state), naming_before)
        with self.assertRaises(ValueError): standards.configure(self.state, {**new, 'rules': []})

    def test_canonical_rename_makes_previous_label_preview_stale(self):
        standards.configure(self.state, config())
        metadata = copy.deepcopy(self.resources)
        metadata['resources'][0].update(label='Fct Orders', tags=['sales'], description='Orders', sample_query_count=1)
        standards.preview(self.state, metadata)
        self.assertEqual(standards.summary(self.state)['status'], 'previewed')
        self.state['workflow']['design']['entities'][0]['name'] = 'renamed_orders'
        self.assertEqual(standards.summary(self.state)['status'], 'stale')

    def test_packet_is_scoped_pinned_and_reports_naming_changes(self):
        standards.configure(self.state, config())
        body = standards.packet(self.state, ['orders'])
        request = {'modeling_standards': body, 'bindings': {'modeling_standards': body['sha256']}}
        self.assertEqual(standards.validate_packet(request), body)
        self.assertEqual(body['rules'][0]['entity_ids'], ['orders'])
        body['rules'][0]['entity_ids'].append('products')
        with self.assertRaises(ValueError): standards.validate_packet(request)
        self.state['workflow']['modeling_standards']['naming_policy_sha256'] = '0'*64
        self.assertEqual(standards.summary(self.state)['status'], 'stale')


class StandardsWorkflowIntegrationTests(unittest.TestCase):
    def test_scoped_context_round_trips_through_execution_receipt(self):
        from test_agent_context import AgentContextTests
        import agent_execution
        import domain_classification as classification
        h = AgentContextTests('test_only_selected_lines_disclosed_with_exact_pins_and_byte_counts')
        h.setUp(); self.addCleanup(h.doCleanups)
        state = {'inputs': {'source': {'fingerprint': {'value': 'a'*64}}}, 'workflow': {'design': {
            'entities': [{'id': 'orders', 'name': 'fct_orders', 'domain': 'sales'}]}}}
        standards.configure(state, config())
        classification.register(state, {'schema_version': 1, 'kind': 'domain_classification', 'version': '1',
            'source_reference': 'synthetic://classification', 'source_sha256': 'a'*64, 'entries': []})
        h.request.update(modeling_standards=standards.packet(state, ['orders']),
                         domain_classification=classification.packet(state, 'sales'))
        for field in ('modeling_standards', 'domain_classification'):
            h.request['bindings'][field] = h.request[field]['sha256']
        receipt = h.build()
        observed = agent_execution.record_execution(h.root/'packet', {'schema_version': 1,
            'kind': 'agent_execution_request', 'task_id': h.request['task_id'], 'run_id': 'run-1',
            'packet_sha256': receipt['packet_sha256'],
            'source_context_receipt_sha256': hashlib.sha256((h.root/'packet/CONTEXT_RECEIPT.json').read_bytes()).hexdigest(),
            'requested_model': None, 'observed_model': None, 'requested_effort': None, 'observed_effort': None,
            'context_mode': 'unknown', 'host_run_reference': None})
        self.assertEqual(observed['context_bindings'], h.request['bindings'])
        self.assertFalse(observed['execution_verified'])

    def test_selected_domain_dispatch_and_tasks_include_only_scoped_context(self):
        import test_domain_workflow as fixtures
        import domain_workflow as domains
        import domain_classification as classification
        import engagement_stages as stages
        h = fixtures.DomainTests('test_discovery_never_selects_or_opens_design')
        h.setUp(); self.addCleanup(h.doCleanups); h.select()
        standards.configure(h.state, config())
        classification.register(h.state, {'schema_version': 1, 'kind': 'domain_classification', 'version': '1',
            'source_reference': 'synthetic://classification',
            'source_sha256': h.state['inputs']['source']['fingerprint']['value'], 'entries': []})
        domains.guard_dispatch(h.state, {'role': 'warehouse_architect', 'scope_ids': ['sales'],
                                        'source_paths': ['orders.sql']})
        h.approve(['orders']); stages.register_tasks(h.state, h.tasks())
        plan = stages.plan_tasks(h.state, h.h.artifacts)
        order_task = next(t for t in plan['tasks'] if t['id'] == 'build-orders')
        self.assertEqual(order_task['modeling_standards']['entity_ids'], ['orders'])
        self.assertEqual(order_task['domain_classification']['domain_id'], 'sales')
        self.assertEqual(domains.public_summary(h.state)['domains'][0]['classification']['status'], 'current')

    def test_guided_actions_preserve_domain_choice_and_project_scoped_preview(self):
        import test_engagement_stages as fixtures
        import delivery_portal as portal
        h = fixtures.StageTests('test_host_attributed_review_opens_candidates_not_deployment')
        h.setUp(); self.addCleanup(h.doCleanups)
        entity = h.state['workflow']['design']['entities'][0]
        doc = config(); doc['rules'][0].update(entity_ids=[entity['id']], domains=[])
        approvals = copy.deepcopy(h.state['workflow']['approvals'])
        h.action('configure-standards', document=doc)
        h.action('preview-standards', document={'schema_version': 1, 'resources': [
            {'id': entity['id'], 'name': entity['name'], 'domain': entity['domain'], 'label': None,
             'tags': [], 'description': None, 'sample_query_count': 0}]})
        h.action('standards-packet', entities=[entity['id']])
        packet = h.state['workflow']['standards_packet']
        self.assertEqual(packet['entity_ids'], [entity['id']])
        self.assertEqual(h.state['workflow']['approvals'], approvals)
        classification = {'schema_version': 1, 'kind': 'domain_classification', 'version': '1',
            'source_reference': 'synthetic://classification',
            'source_sha256': h.state['inputs']['source']['fingerprint']['value'], 'entries': []}
        h.action('register-domain-classification', document=classification)
        h.action('domain-classification-packet', document={'domain_id': entity['domain']})
        self.assertIsNone(h.state['workflow'].get('domain_journey'))
        data = portal._presentation(h.state, None, 'engineer')
        panel = portal._standards_panel(data)
        self.assertIn('Customer standards', panel)
        self.assertIn('modeling-standards', panel)
