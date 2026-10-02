"""Synthetic metadata release planning; no customer connections or approvals."""
import copy
from datetime import datetime, timezone, timedelta
from pathlib import Path
import tempfile
import unittest
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
from ae_common import hash_json
from metadata_contract import build_contract
from metadata_observation import seal, scope, validate_observation, shape_discrepancies
from metadata_observation import physical_union, bind_dbt_manifest
from plan_warehouse_metadata import plan_metadata, verify_plan, export_plan, check_preconditions
from test_metadata_contract import dictionary, configuration


def observation(contract, *, expected=False):
    rows = []
    for resource in contract['resources']:
        if resource['disposition'] == 'ephemeral':
            continue
        def tags(values):
            return [{'name': t['name'], 'value': t['value'], 'application': 'direct'} for t in values] if expected else []
        rows.append({'id': resource['id'], 'relation': copy.deepcopy(resource['relation']),
            'object_version': 'synthetic-object-created-001',
            'comment': resource['description'] if expected else None, 'tags': tags(resource['tags']),
            'columns': [{'name': c['name'], 'data_type': c['data_type'],
                         'comment': c['description'] if expected else None, 'tags': tags(c['tags'])}
                        for c in resource['columns']]})
    return seal({'schema_version': 1, 'kind': 'warehouse_metadata_observation',
        'contract_sha256': contract['contract_sha256'], 'candidate_sha256': contract['configuration']['candidate_sha256'],
        'target': copy.deepcopy(contract['configuration']['target']), 'scope_sha256': hash_json(scope(contract)),
        'release_id': 'synthetic-release-1', 'observed_at': datetime.now(timezone.utc).isoformat(),
        'collection': {'origin': 'simulation', 'complete': True, 'identity_verified': True,
                       'visibility_verified': True, 'query_ids': ['synthetic-query-1'], 'evidence_sha256': 'e'*64},
        'resources': rows, 'governance': []})


def tagged_contract():
    value = dictionary()
    column = value['models'][0]['columns'][0]
    column.update(sensitivity='RESTRICTED', sensitivity_review_status='approved',
                  sensitivity_review_reference='synthetic-security-review',
                  sensitivity_evidence=[{'reference': 'synthetic-classification', 'sha256':'f'*64}])
    config = configuration()
    config['metadata_policy'].update(mode='comments_and_tags', taxonomy='fixture-taxonomy', tag_namespace=['fixture_db', 'governance'])
    tag = {'id': 'sensitivity', 'name': ['fixture_db', 'governance', 'sensitivity'],
           'value': 'RESTRICTED', 'policy_effects': 'none_verified', 'evidence_reference': 'synthetic-policy-review'}
    config['resources'][0]['tags'] = [copy.deepcopy(tag)]
    config['resources'][0]['column_tags'] = {'customer_id': [copy.deepcopy(tag)]}
    return build_contract(value, config)


class MetadataPlanTests(unittest.TestCase):
    def test_comments_plan_all_six_platforms(self):
        for warehouse in ('snowflake', 'databricks', 'bigquery', 'redshift', 'clickhouse', 'motherduck'):
            contract = build_contract(dictionary(), configuration(warehouse))
            result = plan_metadata(contract, observation(contract))
            self.assertEqual(result['status'], 'ready', warehouse)
            self.assertEqual(len(result['operations']), 2)
            self.assertEqual(verify_plan(result), result)
            self.assertTrue(result['read_queries'])
            self.assertTrue(result['privilege_requirements'])

    def test_already_matching_comments_are_no_op(self):
        contract = build_contract(dictionary(), configuration())
        result = plan_metadata(contract, observation(contract, expected=True))
        self.assertEqual(result['status'], 'no_op')
        self.assertEqual(result['operations'], [])
        self.assertEqual(len(result['unchanged']), 2)

    def test_independent_physical_columns_catch_joint_dictionary_yaml_omission(self):
        contract = build_contract(dictionary(), configuration())
        actual = observation(contract)
        actual['resources'][0]['columns'].append({'name': 'hidden_output', 'data_type': 'VARCHAR', 'comment': None, 'tags': []})
        result = plan_metadata(contract, seal(actual))
        self.assertEqual(result['status'], 'blocked')
        self.assertTrue(any('undocumented' in issue for issue in result['blockers']))

    def test_missing_visibility_or_incomplete_result_cannot_pass(self):
        contract = build_contract(dictionary(), configuration())
        for flag in ('complete', 'identity_verified', 'visibility_verified'):
            actual = observation(contract)
            actual['collection'][flag] = False
            self.assertTrue(plan_metadata(contract, seal(actual))['blockers'])

    def test_empty_catalogue_does_not_mean_perfect_coverage(self):
        contract = build_contract(dictionary(), configuration())
        actual = observation(contract); actual['resources'] = []
        self.assertTrue(plan_metadata(contract, seal(actual))['blockers'])

    def test_wrong_target_rejected_even_if_resealed(self):
        contract = build_contract(dictionary(), configuration())
        actual = observation(contract); actual['target']['identity']['principal'] = 'other'
        with self.assertRaisesRegex(ValueError, 'target identity'):
            plan_metadata(contract, seal(actual))

    def test_governed_definition_is_required_and_existing_values_checked(self):
        contract = tagged_contract(); actual = observation(contract)
        result = plan_metadata(contract, actual)
        self.assertEqual(result['status'], 'blocked')
        self.assertTrue(result['governance_requests'])
        actual['governance'] = [{'name':['fixture_db','governance','sensitivity'], 'allowed_values':['PUBLIC'],
                                 'policy_effects':'none_verified', 'evidence_reference':'synthetic'}]
        self.assertTrue(any('conflicts' in s for s in plan_metadata(contract, seal(actual))['blockers']))
        actual['governance'][0]['allowed_values'].append('RESTRICTED')
        self.assertEqual(plan_metadata(contract, seal(actual))['status'], 'ready')
        actual['governance'][0]['policy_effects'] = 'policy_bound'
        self.assertTrue(plan_metadata(contract, seal(actual))['blockers'])

    def test_inherited_tag_does_not_substitute_for_direct_assignment(self):
        contract = tagged_contract(); actual = observation(contract, expected=True)
        actual['governance'] = [{'name':['fixture_db','governance','sensitivity'], 'allowed_values':None,
                                 'policy_effects':'none_verified', 'evidence_reference':'synthetic'}]
        actual['resources'][0]['tags'][0]['application'] = 'inherited'
        result = plan_metadata(contract, seal(actual))
        self.assertEqual(result['counts']['direct_tag_writes'], 1)
        self.assertEqual(result['counts']['native_statements'], 1)

    def test_sensitivity_cannot_be_downgraded(self):
        contract = tagged_contract(); config = copy.deepcopy(contract['configuration'])
        config['resources'][0]['tags'][0]['value'] = 'PUBLIC'
        with self.assertRaisesRegex(ValueError, 'downgrade'):
            build_contract(contract['dictionary'], config)
        config = copy.deepcopy(contract['configuration']); config['resources'][0]['column_tags']['customer_id'][0]['value'] = 'PUBLIC'
        with self.assertRaisesRegex(ValueError, 'canonical classification'):
            build_contract(contract['dictionary'], config)

    def test_resealed_sql_tamper_cannot_become_a_plan(self):
        contract = build_contract(dictionary(), configuration()); result = plan_metadata(contract, observation(contract))
        result['operations'][0]['sql'] = 'DROP TABLE sensitive'
        result['plan_sha256'] = hash_json({k:v for k,v in result.items() if k != 'plan_sha256'})
        with self.assertRaisesRegex(ValueError, 'canonical projection'):
            verify_plan(result)

    def test_concurrent_comment_edit_blocks_overwrite(self):
        contract = build_contract(dictionary(), configuration()); before = observation(contract); result = plan_metadata(contract, before)
        check_preconditions(result, before)
        current = copy.deepcopy(before); current['resources'][0]['comment'] = 'Human changed this'
        with self.assertRaisesRegex(ValueError, 'concurrent metadata drift'):
            check_preconditions(result, seal(current))

    def test_recreated_object_and_stale_observation_block(self):
        contract = build_contract(dictionary(), configuration()); before = observation(contract); result = plan_metadata(contract, before)
        current = copy.deepcopy(before); current['resources'][0]['object_version'] = 'replacement'
        with self.assertRaisesRegex(ValueError, 'recreated'):
            check_preconditions(result, seal(current))
        with self.assertRaisesRegex(ValueError, 'stale'):
            check_preconditions(result, before, now=datetime.now(timezone.utc)+timedelta(hours=1))

    def test_partial_completion_rechecks_actual_values(self):
        contract = build_contract(dictionary(), configuration()); before = observation(contract); result = plan_metadata(contract, before)
        done = result['operations'][0]
        current = copy.deepcopy(before); current['resources'][0]['comment'] = done['after']
        check_preconditions(result, seal(current), completed=[done['id']])
        with self.assertRaisesRegex(ValueError, 'concurrent metadata drift'):
            check_preconditions(result, before, completed=[done['id']])

    def test_blocked_plan_does_not_export_runnable_sql(self):
        contract = build_contract(dictionary(False), configuration()); result = plan_metadata(contract, observation(contract))
        with tempfile.TemporaryDirectory() as root:
            output = Path(root).resolve()/'metadata'
            export_plan(result, output)
            self.assertEqual(list(output.rglob('*.sql')), [])
            self.assertTrue((output/'metadata-plan.json').exists())

    def test_physical_reconciler_reuses_model_source_union(self):
        contract = build_contract(dictionary(), configuration())
        self.assertTrue(physical_union(contract, observation(contract))['passed'])
        actual = observation(contract)
        actual['resources'][0]['columns'].append({'name':'omitted','data_type':'VARCHAR','comment':None,'tags':[]})
        self.assertFalse(physical_union(contract, seal(actual))['passed'])

    def test_dbt_full_build_denominator_includes_sources(self):
        contract = build_contract(dictionary(), configuration())
        node = {'resource_type':'model', 'database':'fixture_db', 'schema':'gold', 'alias':'fact_customer', 'config':{}}
        manifest = {'nodes': {'m':node}, 'sources': {}}
        self.assertEqual(bind_dbt_manifest(contract, manifest)['relations'], 1)
        manifest['sources']['s'] = {'resource_type':'source','database':'fixture_db','schema':'raw','identifier':'customer','config':{}}
        with self.assertRaisesRegex(ValueError, 'full enabled dbt build'):
            bind_dbt_manifest(contract, manifest)

    def test_reported_blind_run_scale_without_customer_data(self):
        value = dictionary(); base = copy.deepcopy(value['models'][0]); value['models'] = []
        config = configuration(); template = copy.deepcopy(config['resources'][0]); config['resources'] = []
        for number in range(27):
            model = copy.deepcopy(base); model['model_id'] = 'synthetic.model.'+str(number); model['columns'] = []
            binding = copy.deepcopy(template); binding['resource_id'] = model['model_id']; binding['relation']['name'] = 'model_'+str(number); binding['columns'] = {}
            for index in range(48 if number < 13 else 47):
                column = copy.deepcopy(base['columns'][0]); column['name'] = 'Column_'+str(index)
                column['column_id'] = model['model_id'] + ':' + column['name']; column['description'] = "Reviewed synthetic text — 雪; customer's field."
                model['columns'].append(column); binding['columns'][column['name']] = column['name']
            value['models'].append(model); config['resources'].append(binding)
        source = copy.deepcopy(base); source.pop('model_id'); source['source_id'] = 'source.synthetic.raw'; source['columns'] = []
        binding = copy.deepcopy(template); binding.update(resource_id=source['source_id'],resource_type='source',layer='raw',source_write_decision='synthetic-source-owner'); binding['relation']['namespace'][-1] = 'raw'; binding['columns'] = {}
        for index in range(497):
            column = copy.deepcopy(base['columns'][0]); column['name'] = 'RawColumn_'+str(index); column['column_id'] = 'raw:'+str(index)
            column['source_refs'] = [{'object_id':source['source_id'],'column_path':[column['name']],'catalogue_sha256':config['catalogue_sha256']}]
            source['columns'].append(column); binding['columns'][column['name']] = column['name']
        value.update(sources=[source],source_inventory_sha256='d'*64); config['resources'].append(binding)
        config['metadata_policy'].update(raw_comments=True,source_ids=[source['source_id']])
        self.assertEqual(sum(len(m['columns']) for m in value['models']),1282)
        contract = build_contract(value,config); before = observation(contract)
        result = plan_metadata(contract,before)
        self.assertEqual(result['status'],'ready')
        self.assertEqual(result['counts']['comment_writes'],1282+497+28)
        self.assertEqual(sum(o['phase']=='source_metadata' for o in result['operations']),498)
        self.assertEqual(physical_union(contract,before)['columns'],1779)


if __name__ == '__main__':
    unittest.main()
