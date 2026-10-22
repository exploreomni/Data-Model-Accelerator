"""Public compatibility is reviewed separately from source fidelity and SQL validity."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import consumer_contracts as contracts
import engagement_stages as stages
import test_engagement_stages as fixtures


class ConsumerContractTests(unittest.TestCase):
    def setUp(self):
        self.h = fixtures.StageTests('test_host_attributed_review_opens_candidates_not_deployment')
        self.h.setUp(); self.addCleanup(self.h.doCleanups)
        self.state = self.h.state
        entity = self.h.doc['entities'][1]
        self.row = dict(id='orders-public-v1', source_id='legacy:orders', entity_id='orders',
            consumer_ids=['dashboard-orders'], baseline=dict(columns=copy.deepcopy(entity['columns']),
                materialization='table',grain=entity['grain'],history=entity['history'],access=entity['security']),
            proposed_materialization='table',evidence_refs=['synthetic://legacy/schema'])

    def register(self):
        return contracts.register(self.state, {'schema_version':1,'contracts':[self.row]}, self.h.artifacts)

    def test_removed_fields_and_table_to_view_require_scoped_decision(self):
        self.row['baseline']['columns'].append(dict(name='customer_name',type='string',description='Public name'))
        self.row['proposed_materialization']='view'
        summary=self.register(); kinds={f['kind'] for f in summary['rows'][0]['findings']}
        self.assertTrue({'public_field_removed','materialization_changed'} <= kinds)
        self.assertTrue(contracts.gaps(self.state,['orders']))
        self.assertFalse(contracts.gaps(self.state,['products']))
        request=dict(schema_version=1,contract_ids=[self.row['id']],decision='accept_changes',
            reviewer='Synthetic reviewer',review_reference='synthetic://review/1',
            bindings=contracts.review_bindings(self.state,[self.row['id']]))
        contracts.review(self.state,request)
        self.assertFalse(contracts.gaps(self.state,['orders']))
        self.assertEqual(stages.approved_entities(self.state),set())
        self.state['workflow']['design']['entities'][1]['grain']='One row per order line'
        self.assertTrue(contracts.gaps(self.state,['orders']))
        with self.assertRaisesRegex(ValueError,'stale'): contracts.review(self.state,request)

    def test_registration_is_additive_idempotent_and_freezes_baseline(self):
        self.register(); self.register()
        self.assertEqual(len(self.state['workflow']['consumer_contracts']['history']),1)
        before=copy.deepcopy(self.row)
        self.row['baseline']['columns']=[]
        with self.assertRaisesRegex(ValueError,'frozen baseline'): self.register()
        self.row=before; self.row['consumer_ids']=[]
        with self.assertRaisesRegex(ValueError,'disappear'): self.register()
        self.assertEqual(contracts.summarize(self.state)['counts']['contracts'],1)

    def test_unknown_materialization_and_prose_do_not_claim_parity(self):
        self.row['proposed_materialization']=None
        summary=self.register(); findings=summary['rows'][0]['findings']
        self.assertTrue(any(f['kind']=='materialization_unverified' and not f['requires_decision'] for f in findings))
        self.assertTrue(any(f['kind']=='description_meaning_unverified' for f in findings))
        self.assertEqual(summary['rows'][0]['status'],'no_structural_changes_observed')
        contracts.review(self.state,dict(schema_version=1,contract_ids=[self.row['id']],decision='requires_fix',
            reviewer='Synthetic reviewer',review_reference='synthetic://review/negative',
            bindings=contracts.review_bindings(self.state,[self.row['id']])))
        self.assertTrue(contracts.gaps(self.state,['orders']))

    def test_description_conflicts_are_read_only_and_sql_changes_invalidate_review(self):
        try: import sqlglot
        except ImportError: self.skipTest('Optional SQL reader unavailable')
        entity=self.state['workflow']['design']['entities'][1]
        entity['columns'].append(dict(name='financial_month',type='integer',description='Months since first financial month'))
        self.row['definition_checks']=[dict(column='financial_month',query_path='orders.sql',
            expression_output='financial_month',described_references=['first_financial_month'])]
        path=self.h.artifacts/'orders.sql'
        sql="select date_diff(current_date(), customer_created_month, month) as financial_month from {{ ref('customers') }}"
        path.write_text(sql); self.state['answers']['warehouse']='bigquery'
        summary=self.register()
        self.assertEqual(path.read_text(),sql)
        self.assertTrue(any(f['kind']=='description_expression_conflict' for f in summary['rows'][0]['findings']))
        before=contracts.review_bindings(self.state,[self.row['id']])
        path.write_text(sql.replace('customer_created_month','first_financial_month'))
        self.assertNotEqual(before,contracts.review_bindings(self.state,[self.row['id']]))
        observed=contracts.summarize(self.state)['rows'][0]['definition_checks'][0]['observation']
        self.assertEqual(observed['status'],'references_consistent')
        self.assertIn('does not',observed['qualification'])
        path.write_text('with unused as (select first_financial_month as financial_month from source) select wrong_id as actual_id from other_source')
        observed=contracts.summarize(self.state)['rows'][0]['definition_checks'][0]['observation']
        self.assertEqual(observed['status'],'unverified')

    def test_unsupported_templates_and_unsafe_paths_never_execute(self):
        self.row['definition_checks']=[dict(column='orders_id',query_path='orders.sql',
            expression_output='orders_id',described_references=['source_id'])]
        (self.h.artifacts/'orders.sql').write_text("select {{ dangerous_macro() }} as orders_id")
        observation=self.register()['rows'][0]['definition_checks'][0]['observation']
        self.assertEqual(observation['status'],'unverified')
        self.row['definition_checks'][0]['query_path']='../source/orders.sql'
        with self.assertRaises(ValueError): self.register()
        self.row.pop('definition_checks'); self.row['source_id']='/Users/synthetic/private/model.sql'
        with self.assertRaises(ValueError): self.register()

    def test_consumer_changes_stale_only_affected_entity(self):
        self.register(); before=stages.entity_bindings(self.state,['orders','products'])
        self.row['proposed_materialization']='view'; self.register()
        after=stages.entity_bindings(self.state,['orders','products'])
        self.assertNotEqual(before['orders'],after['orders'])
        self.assertEqual(before['products'],after['products'])

    def test_cli_and_provisional_generation_remain_available(self):
        self.row['proposed_materialization']='view'
        self.row['definition_checks']=[dict(column='orders_id',query_path='orders.sql',
            expression_output='orders_id',described_references=['source_id'])]
        self.h.action('record-consumer-contracts',document={'schema_version':1,'contracts':[self.row]},artifact_root=self.h.artifacts)
        state=self.h.state
        self.assertTrue(contracts.gaps(state,['orders']))
        stages.record_draft_request(state,['orders'],dict(schema_version=1,kind='provisional_code_request',
            requester='Synthetic user',request_reference='synthetic://draft',request_text='Generate provisional code.',
            bindings=stages.draft_bindings(state,['orders'])))
        self.assertIn('orders',stages.require_stage(state,'implementation',['orders']))
        pins=stages.draft_bindings(state,['orders'])
        (self.h.artifacts/'orders.sql').write_text('select source_id as orders_id from source_orders')
        self.assertEqual(pins,stages.draft_bindings(state,['orders']))
        self.assertIn('orders',stages.require_stage(state,'implementation',['orders']))
        self.assertEqual(stages.approved_entities(state),set())


if __name__=='__main__': unittest.main()
