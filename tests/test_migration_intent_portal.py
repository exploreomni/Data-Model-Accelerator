"""Architecture intent is a separate, scoped explanation, never a pass badge."""
import copy
import json
import shutil
import unittest

import test_domain_review_export as partitions
import test_portal_navigation as navigation
import migration_intent
import domain_review_export
import portal_checks

portal = navigation.portal


def public_intent():
    return {'schema_version': 1, 'status': 'recorded',
            'qualification': 'Host-attributed architecture review only; source roles are declared.',
            'native_validation': 'not_established', 'business_acceptance': 'not_established',
            'domains': [{'domain_id': 'sales', 'status': 'partial', 'structural_objective': 'refactor',
                'behavior': 'preserve', 'model_ids': ['gold.orders'], 'objective_ids': ['reduce-copying'],
                'gaps': ['transitional_dependencies_outstanding', 'architecture_assessment_missing'],
                'transitional_dependency_count': 2, 'semantic_purpose_count': 1,
                'model_disposition_counts': {'create': 1, 'reuse': 2, 'extend': 3, 'replace': 4, 'undetermined': 5},
                'review_authority': 'host_attributed_not_authenticated'}]}


class IntentProjectionTests(unittest.TestCase):
    def test_private_fields_and_completion_boolean_are_not_transported(self):
        value = public_intent(); before = copy.deepcopy(value)
        value['source_path'] = 'PRIVATE_ROOT'; row = value['domains'][0]
        row.update(source_roles=[{'path_prefix': 'PRIVATE_SOURCE'}], review_reference='PRIVATE_REVIEW', refactor_complete=True)
        row['model_disposition_counts']['private'] = 99
        result = portal._workflow_presentation({'migration_intent': value})['migration_intent']
        self.assertEqual(result, before)
        self.assertNotIn('PRIVATE_', json.dumps(result))
        self.assertNotIn('refactor_complete', json.dumps(result))
        value['domains'][0]['model_disposition_counts'].update(create=True, reuse=-1, extend='3')
        self.assertEqual(portal._intent_presentation(value)['domains'][0]['model_disposition_counts'], {'replace': 4, 'undetermined': 5})

    def test_actual_summary_and_partition_scope_are_retained(self):
        fixture = partitions.DomainReviewExportTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        migration_intent.configure(fixture.state, {'schema_version': 1, 'kind': 'migration_intent',
            'domain_id': 'returns', 'structural_objective': 'refactor', 'behavior': 'preserve',
            'objectives': [{'id': 'shape', 'statement': 'Review target shape independently from behavior.'}],
            'source_roles': [{'id': 'legacy', 'root_id': 'primary', 'role': 'legacy_baseline', 'path_prefix': 'source.sql'}],
            'behavior_constraints': ['Preserve declared population'], 'request_reference': 'synthetic://intent-only'})
        plans = domain_review_export.plan_partitions(fixture.state)['partitions']
        returns = next(row for row in plans if row['domain'] == 'returns')
        data = portal._presentation(fixture.state, returns['review'])
        summary = data['workflow']['migration_intent']
        self.assertEqual([row['domain_id'] for row in summary['domains']], ['returns'])
        self.assertEqual(summary['domains'][0]['model_disposition_counts'], {
            'create': 1, 'reuse': 0, 'extend': 0, 'replace': 0, 'undetermined': 1})
        self.assertEqual(summary['domains'][0]['status'], 'unassessed')
        self.assertNotIn('source.sql', json.dumps(summary))
        sales = next(row for row in plans if row['domain'] == 'sales')
        scoped = portal._presentation(fixture.state, sales['review'])['workflow']['migration_intent']
        self.assertEqual(scoped['domains'], [])
        portal._trim_workflow_details(data)
        self.assertNotIn('migration_intent', data['workflow'])


@unittest.skipUnless(shutil.which('node'), 'Node required for offline DOM checks')
class IntentPortalTests(unittest.TestCase):
    page = navigation.PortalNavigationTests.page

    def payload(self):
        data = navigation.PortalNavigationTests.payload(self)
        data['workflow'] = {'migration_intent': portal._intent_presentation(public_intent())}
        return data

    def test_counts_transitions_and_gaps_are_separate_from_readiness(self):
        self.page(self.payload(), """
const content=node=>[node.textContent,...node.children.map(content)].join(' ');
assert.equal(el('architecture-intent').hidden,false);
const value=content(el('architecture-intent-domains'));
assert.match(value,/sales · refactor/);assert.match(value,/Conformance review: partial/);
assert.match(value,/create: 1 · reuse: 2 · extend: 3 · replace: 4 · undetermined: 5/);
assert.match(value,/Transitional dependencies: 2/);assert.match(value,/Behavior: preserve/);
assert.match(value,/transitional dependencies outstanding/);assert.match(value,/architecture assessment missing/);
assert.match(el('architecture-intent-note').textContent,/grants no approval or completion authority/);
assert.match(el('architecture-intent-note').textContent,/Native validation and business acceptance remain separate/);
assert.doesNotMatch(value,/complete|passed|validated/);
const snapshot=JSON.parse(JSON.stringify(data));trimWorkflowDetails(snapshot,new Set(['implementation']));
assert.equal(snapshot.workflow.migration_intent,undefined);
workflow.migration_intent.domains=[];renderArchitectureIntent();
assert.match(content(el('architecture-intent-domains')),/unassessed in the included scope/);
""")

    def test_untrusted_text_is_plain_and_audit_stays_hidden(self):
        data = self.payload()
        data['workflow']['migration_intent']['domains'][0]['domain_id'] = '<img src=x onerror=alert(1)>'
        self.page(data, """
const content=node=>[node.textContent,...node.children.map(content)].join(' ');
assert.match(content(el('architecture-intent-domains')),/<img src=x/);
assert.equal(el('architecture-intent-domains').querySelector('img'),null);
data.audience='audit';renderArchitectureIntent();assert.equal(el('architecture-intent').hidden,true);
""")


if __name__ == '__main__':
    unittest.main()
