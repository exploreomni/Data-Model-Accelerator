"""Naming candidates preserve reviewed identities; no project or warehouse writes."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
from ae_common import hash_json
from metadata_naming import preview_naming


def resource(identifier='model.customer', **changes):
    value = {'resource_id': identifier, 'relation': {'namespace': ['Fixture DB', 'Gold'], 'name': 'draft_customer', 'kind': 'table'},
             'is_new': True, 'explicit_alias': False, 'model_role': 'FACT', 'stem': 'customer'}
    value.update(changes)
    return value


POLICY = {'mode': 'type_domain', 'domain': 'sales', 'decision_reference': 'synthetic-naming-decision'}
TYPE_MAP = {'schema_version': 1, 'kind': 'metadata_naming_type_map', 'review_status': 'approved',
            'decision_reference': 'synthetic-type-map-review', 'prefixes': {'FACT': 'FCT', 'DIMENSION': 'DIM'}}


class MetadataNamingTests(unittest.TestCase):
    def preview(self, rows=None, *, warehouse='snowflake', policy=None, **kwargs):
        return preview_naming(warehouse, [resource()] if rows is None else rows,
                              POLICY if policy is None else policy, type_map=kwargs.pop('type_map', TYPE_MAP), **kwargs)

    def test_default_preserves_exact_names_on_every_supported_platform(self):
        for warehouse in ('snowflake', 'databricks', 'bigquery', 'redshift', 'clickhouse', 'motherduck'):
            value = resource(model_role='UNKNOWN', stem=None)
            if warehouse == 'clickhouse':
                value['relation']['namespace'] = ['Fixture DB']
            with self.subTest(warehouse=warehouse):
                result = preview_naming(warehouse, [value])
                self.assertEqual(result['status'], 'preserved')
                self.assertEqual(result['mapping'][0]['before'], result['mapping'][0]['proposed'])
                self.assertFalse(result['execution_authorized'])

    def test_new_snowflake_name_uses_only_supplied_role_stem_and_domain(self):
        result = self.preview()
        row = result['mapping'][0]
        self.assertEqual(row['proposed']['name'], 'FCT_SALES_CUSTOMER')
        self.assertEqual(row['proposed']['namespace'], ['Fixture DB', 'Gold'])
        self.assertEqual(row['quoting'], 'exact_components')
        self.assertEqual(result['status'], 'review_required')
        self.assertEqual(result['type_map_decision_reference'], TYPE_MAP['decision_reference'])
        self.assertFalse(result['native_qualified'])

    def test_existing_models_and_new_explicit_aliases_win(self):
        old = resource('old', is_new=False, stem=None, model_role='UNKNOWN')
        old['relation']['name'] = 'Human "Alias 雪'
        explicit = resource('explicit', explicit_alias=True)
        explicit['relation']['name'] = 'CURRENT_DATE'
        result = self.preview([old, explicit])
        self.assertEqual(result['status'], 'preserved')
        rows = {r['resource_id']: r for r in result['mapping']}
        self.assertEqual(rows['old']['proposed'], old['relation'])
        self.assertEqual(rows['old']['reason'], 'existing_resource')
        self.assertEqual(rows['explicit']['proposed']['name'], 'CURRENT_DATE')
        self.assertEqual(rows['explicit']['reason'], 'explicit_alias')

    def test_no_prefix_is_inferred_from_name_or_unknown_role(self):
        for role in ('UNKNOWN', 'BRIDGE'):
            result = self.preview([resource(model_role=role)])
            self.assertEqual(result['status'], 'blocked')
            self.assertEqual(result['mapping'][0]['proposed']['name'], 'draft_customer')
            self.assertTrue(any('type map' in issue for issue in result['blockers']))

    def test_missing_review_decisions_and_unreviewed_type_maps_are_rejected(self):
        for value in [None, dict(TYPE_MAP, review_status='proposed'), dict(TYPE_MAP, decision_reference=''),
                      dict(TYPE_MAP, prefixes={'UNKNOWN': 'FCT'}), dict(TYPE_MAP, schema_version=True)]:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.preview(type_map=value)
        with self.assertRaises(ValueError):
            self.preview(policy=dict(POLICY, decision_reference=None))

    def test_snowflake_limit_is_255_characters_without_truncation(self):
        prefix = len('FCT_SALES_')
        okay = self.preview([resource(stem='x'*(255-prefix))])
        self.assertEqual(len(okay['mapping'][0]['proposed']['name']), 255)
        self.assertEqual(okay['status'], 'review_required')
        long = self.preview([resource(stem='x'*(256-prefix))])
        self.assertEqual(long['status'], 'blocked')
        self.assertTrue(any('no truncation' in issue for issue in long['blockers']))
        old = resource(is_new=False)
        old['relation']['name'] = 'x'*256
        with self.assertRaisesRegex(ValueError, 'identifier'):
            self.preview([old])

    def test_literal_stems_reject_templates_and_sql_instead_of_sanitizing(self):
        for stem in [None, '', 'space here', 'a.b', 'x;DROP TABLE x', '{{ var("x") }}', '雪', 'x\nname']:
            with self.subTest(stem=stem):
                result = self.preview([resource(stem=stem)])
                self.assertEqual(result['status'], 'blocked')
                self.assertFalse(result['mapping'][0]['changed'])
        for field, value in [('domain', 'a.b'), ('domain', '{{x}}')]:
            with self.assertRaises(ValueError):
                self.preview(policy=dict(POLICY, **{field: value}))

    def test_collisions_cover_case_normalization_aliases_and_occupied_inventory(self):
        one = resource('one', stem='customer')
        two = resource('two', stem='CUSTOMER')
        self.assertEqual(self.preview([one, two])['status'], 'blocked')
        explicit = resource('explicit', explicit_alias=True)
        explicit['relation']['name'] = 'FCT_SALES_CUSTOMER'
        self.assertEqual(self.preview([one, explicit])['status'], 'blocked')
        occupied = copy.deepcopy(explicit['relation'])
        self.assertEqual(self.preview([one], occupied_relations=[occupied])['status'], 'blocked')
        old = resource(is_new=False)
        self.assertEqual(self.preview([old], occupied_relations=[old['relation']])['status'], 'preserved')

    def test_supplied_namespaces_are_not_merged_or_normalized(self):
        one, two = resource('one'), resource('two')
        two['relation']['namespace'][-1] = 'Silver'
        result = self.preview([one, two])
        self.assertEqual(result['status'], 'review_required')
        self.assertEqual([r['proposed']['namespace'][-1] for r in result['mapping']], ['Gold', 'Silver'])

    def test_versions_need_explicit_distinct_stems_not_an_invented_suffix(self):
        one, two = resource('model.customer.v1'), resource('model.customer.v2')
        result = self.preview([one, two])
        self.assertEqual(result['status'], 'blocked')
        two['stem'] = 'customer_v2'
        result = self.preview([one, two])
        self.assertEqual(result['status'], 'review_required')
        self.assertEqual(result['mapping'][1]['proposed']['name'], 'FCT_SALES_CUSTOMER_V2')

    def test_other_platform_and_layer_domain_renames_remain_blocked(self):
        for warehouse in ('databricks', 'bigquery', 'redshift', 'clickhouse', 'motherduck'):
            value = resource()
            if warehouse == 'clickhouse':
                value['relation']['namespace'] = ['db']
            result = self.preview([value], warehouse=warehouse)
            self.assertEqual(result['status'], 'blocked')
            self.assertFalse(result['mapping'][0]['changed'])
        self.assertEqual(self.preview(policy=dict(POLICY, mode='layer_domain'))['status'], 'blocked')

    def test_input_is_not_mutated_and_hashes_change_with_reviewed_decisions(self):
        rows = [resource()]
        original = copy.deepcopy(rows)
        a = self.preview(rows)
        self.assertEqual(rows, original)
        self.assertEqual(a, self.preview(rows))
        self.assertEqual(a['preview_sha256'], hash_json({k:v for k,v in a.items() if k != 'preview_sha256'}))
        b = self.preview(rows, policy=dict(POLICY, decision_reference='changed-review'))
        self.assertNotEqual(a['preview_sha256'], b['preview_sha256'])
        changed = copy.deepcopy(TYPE_MAP); changed['prefixes']['FACT'] = 'FACT'
        self.assertNotEqual(a['preview_sha256'], self.preview(rows, type_map=changed)['preview_sha256'])

    def test_input_order_does_not_change_the_mapping_or_digest(self):
        one, two = resource('one'), resource('two', stem='orders')
        self.assertEqual(self.preview([one, two]), self.preview([two, one]))

    def test_flags_namespaces_and_unknown_fields_are_not_guessed(self):
        for row in [resource(is_new='yes'), resource(explicit_alias=1), resource(model_role='ORDER'),
                    dict(resource(), custom_alias_macro='execute_me'),
                    resource(relation={'namespace': ['db.schema'], 'name': 'orders', 'kind': 'table'})]:
            with self.subTest(row=row):
                with self.assertRaises(ValueError):
                    self.preview([row])
        with self.assertRaisesRegex(ValueError, 'Duplicate naming resource'):
            self.preview([resource(), resource()])

    def test_nonphysical_resources_cannot_receive_native_naming(self):
        row = resource()
        row['relation']['kind'] = 'ephemeral'
        self.assertEqual(self.preview([row])['status'], 'blocked')


if __name__ == '__main__':
    unittest.main()
