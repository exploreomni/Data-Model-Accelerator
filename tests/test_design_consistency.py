"""Synthetic structural diagnostics; no source SQL or warehouse execution."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import design_consistency as consistency
from ae_common import hash_json


def candidate():
    def entity(name, parents):
        return {'id': name, 'name': name, 'domain': 'commerce', 'layer': 'gold',
                'grain': 'One row per ' + name, 'keys': [name + '_id'],
                'columns': [{'name': name + '_id', 'type': 'integer', 'description': 'Stable key'}],
                'depends_on': parents, 'asset_ids': [], 'security': 'Unresolved',
                'history': 'Current state', 'disposition': 'create', 'reuse': None,
                'source_paths': [], 'catalogue_pointers': []}
    return {'schema_version': 1, 'id': 'commerce', 'revision': 1,
            'entities': [entity('customers', []), entity('orders', ['customers'])],
            'relationships': [{'from': 'orders', 'to': 'customers', 'kind': 'relationship',
                               'cardinality': 'many_to_one'}],
            'assets': [], 'decisions': [], 'existing_models': []}


def codes(report, field='findings'):
    return {row['code'] for row in report[field]}


class DesignConsistencyTests(unittest.TestCase):
    def test_legacy_design_remains_consistent_without_physical_claims(self):
        report = consistency.assess_design(candidate())
        self.assertEqual(report['status'], 'consistent')
        self.assertEqual(report['findings'], [])
        self.assertTrue({'relationship_columns_unknown', 'physical_validation_unknown',
                         'business_validation_unknown'} <= codes(report, 'unknowns'))
        self.assertEqual(report['authority'], {'authoring': False, 'deployment': False})

    def test_bindings_track_exact_bytes_and_canonical_design(self):
        design = candidate()
        raw = json.dumps(design, indent=2).encode()
        report = consistency.assess_design(raw)
        compact = consistency.assess_design(json.dumps(design).encode())
        self.assertEqual(report['input_sha256'], hashlib.sha256(raw).hexdigest())
        self.assertNotEqual(report['input_sha256'], compact['input_sha256'])
        self.assertEqual(report['design_binding']['sha256'], hash_json(design))
        self.assertEqual(report['design_binding'], compact['design_binding'])
        design['sha256'] = hash_json(design)
        self.assertEqual(consistency.assess_design(design)['findings'], [])
        design['entities'][0]['grain'] = 'Changed grain'
        self.assertIn('design_hash_mismatch', codes(consistency.assess_design(design)))

    def test_duplicate_ids_and_model_names_do_not_overwrite_each_other(self):
        design = candidate()
        duplicate = copy.deepcopy(design['entities'][0])
        duplicate['domain'] = 'other-domain'
        design['entities'].append(duplicate)
        report = consistency.assess_design(design)
        self.assertTrue({'duplicate_entity_id', 'duplicate_model_name'} <= codes(report))
        design['entities'][-1]['id'] = 'customers-silver'
        design['entities'][-1]['layer'] = 'silver'
        self.assertNotIn('duplicate_model_name', codes(consistency.assess_design(design)))

    def test_existing_inventory_can_share_a_target_reuse_name(self):
        design = candidate()
        design['existing_models'] = [{'id': 'source-customers', 'name': 'customers'}]
        self.assertNotIn('duplicate_model_name', codes(consistency.assess_design(design)))
        design['existing_models'].append({'id': 'another-source', 'name': 'customers'})
        self.assertIn('duplicate_existing_model_name', codes(consistency.assess_design(design)))

    def test_duplicate_columns_placeholder_and_missing_dependencies(self):
        design = candidate()
        design['entities'][1]['columns'] += [
            {'name': 'orders_id', 'type': 'integer'}, {'name': '<column_name>', 'type': '<type>'}]
        design['entities'][1]['depends_on'] += ['absent']
        report = consistency.assess_design(design)
        self.assertTrue({'duplicate_column_name', 'placeholder_column_name',
                         'placeholder_column_type', 'unknown_dependency'} <= codes(report))

    def test_quoted_identifiers_and_unknown_types_are_preserved(self):
        design = candidate()
        design['entities'][0]['columns'] += [
            {'name': '"Customer Name"', 'type': 'VARCHAR(100)'},
            {'name': 'Customer Segment', 'type': 'UNKNOWN'},
            {'name': '`TODO`', 'type': 'custom_type'}]
        report = consistency.assess_design(design)
        self.assertEqual(report['findings'], [])
        self.assertIn('column_type_unknown', codes(report, 'unknowns'))

    def test_explicit_key_binding_checks_names_arity_and_declared_primary_key(self):
        design = candidate()
        edge = design['relationships'][0]
        edge.update(from_columns=['missing_fk'], to_columns=['missing_pk'])
        report = consistency.assess_design(design)
        self.assertIn('relationship_column_missing', codes(report))
        edge.update(from_columns=['orders_id'], to_columns=['customers_id'])
        self.assertEqual(consistency.assess_design(design)['findings'], [])
        design['entities'][0]['columns'].append({'name': 'name', 'type': 'text'})
        edge['to_columns'] = ['name']
        report = consistency.assess_design(design)
        self.assertEqual(report['findings'], [])
        self.assertIn('relationship_key_mismatch', codes(report, 'unknowns'))
        edge['to_columns'] = ['customers_id', 'name']
        self.assertIn('relationship_binding_arity', codes(consistency.assess_design(design)))

    def test_compound_keys_can_reorder_but_cannot_omit_components(self):
        design = candidate()
        customer, order = design['entities']
        customer['columns'].append({'name': 'tenant_id', 'type': 'integer'})
        order['columns'].append({'name': 'tenant_id', 'type': 'integer'})
        customer['keys'].append('tenant_id')
        design['relationships'][0].update(from_columns=['tenant_id', 'orders_id'],
                                          to_columns=['tenant_id', 'customers_id'])
        self.assertEqual(consistency.assess_design(design)['findings'], [])
        design['relationships'][0].update(from_columns=['orders_id'], to_columns=['customers_id'])
        self.assertIn('relationship_key_mismatch', codes(consistency.assess_design(design), 'unknowns'))

    def test_incomplete_inventory_markers_are_unknown_and_quoted_names_are_literal(self):
        for name in ('*', '(all columns)', 'same columns as source_orders'):
            with self.subTest(name=name):
                design = candidate()
                design['entities'][0]['columns'] = [{'name': name, 'type': 'UNKNOWN'}]
                design['relationships'][0].update(from_columns=['orders_id'], to_columns=['customers_id'])
                report = consistency.assess_design(design)
                self.assertEqual(report['findings'], [])
                self.assertIn('column_inventory_unknown', codes(report, 'unknowns'))
                self.assertIn('key_binding_unknown', codes(report, 'unknowns'))
        design = candidate()
        design['entities'][0]['columns'].append({'name': '"*"', 'type': 'integer'})
        self.assertNotIn('column_inventory_unknown', codes(consistency.assess_design(design), 'unknowns'))

    def test_column_bound_matches_existing_per_entity_limit(self):
        design = candidate()
        for entity in design['entities']:
            entity['columns'] += [{'name': 'column_' + str(number), 'type': 'integer'} for number in range(10001)]
        self.assertEqual(consistency.assess_design(design)['findings'], [])

    def test_predicate_strings_are_not_invented_into_column_bindings(self):
        design = candidate()
        design['relationships'][0]['predicate'] = 'coalesce(orders.absent, 0) = customers.absent'
        report = consistency.assess_design(design)
        self.assertEqual(report['findings'], [])
        self.assertIn('relationship_columns_unknown', codes(report, 'unknowns'))
        design['relationships'][0]['predicate'] = {
            'from_columns': ['orders_id'], 'to_columns': ['absent']}
        self.assertIn('relationship_column_missing', codes(consistency.assess_design(design)))

    def test_key_and_relationship_endpoint_mismatches_are_diagnostic(self):
        design = candidate()
        design['entities'][0]['keys'] = ['absent']
        design['relationships'][0]['to'] = 'absent'
        report = consistency.assess_design(design)
        self.assertTrue({'key_column_missing', 'unknown_relationship_endpoint'} <= codes(report))

    def test_projection_is_independent_and_keeps_exact_names_and_unknowns(self):
        design = candidate()
        design['entities'][0]['columns'][0]['type'] = 'UNKNOWN'
        before = copy.deepcopy(design)
        projection = consistency.project_review(design)
        self.assertEqual(projection['models'][0]['name'], 'customers')
        self.assertEqual(projection['relationships'], design['relationships'])
        self.assertEqual(projection['dictionary_fields'], [
            'model_id', 'model_name', 'layer', 'domain', 'grain', 'column_name', 'data_type', 'key', 'description'])
        self.assertEqual(projection['dictionary_rows'][0][6], 'UNKNOWN')
        self.assertEqual(consistency.compare_review(design, projection)['findings'], [])
        projection['models'][0]['columns'][0]['name'] = 'changed'
        self.assertEqual(design, before)

    def test_projection_carries_assets_and_preserves_unmapped_status(self):
        design = candidate()
        design['assets'] = [{'id': 'report:customers', 'name': 'Customer report', 'kind': 'report',
                             'mapping_status': 'unmapped', 'evidence_refs': ['source:inventory']}]
        design['entities'][0]['asset_ids'] = ['report:customers']
        before = copy.deepcopy(design)
        projection = consistency.project_review(design)
        self.assertEqual(projection['assets'], design['assets'])
        self.assertTrue(set(projection['models'][0]['asset_ids']) <= {row['id'] for row in projection['assets']})
        self.assertEqual(projection['assets'][0]['mapping_status'], 'unmapped')
        projection['assets'][0]['evidence_refs'].append('changed')
        self.assertEqual(design, before)
        design['assets'].append(None)
        with self.assertRaisesRegex(ValueError, 'assets'):
            consistency.project_review(design)

    def test_review_comparison_checks_actual_content_despite_matching_binding(self):
        design = candidate()
        review = consistency.project_review(design)
        review['models'][0].update(name='wrong', grain='Wrong grain', layer='bronze')
        review['models'][1]['columns'][0]['name'] = 'wrong_column'
        review['relationships'][0]['cardinality'] = 'one_to_many'
        report = consistency.compare_review(design, review)
        self.assertTrue({'review_model_mismatch', 'review_columns_mismatch',
                         'review_relationships_mismatch'} <= codes(report))
        self.assertEqual(report['review_sha256'], hash_json(review))

    def test_review_tolerates_presentation_fields_order_and_unsupplied_knowledge(self):
        design = candidate()
        review = consistency.project_review(design)
        review['models'].reverse()
        review['models'][0]['ui_color'] = 'blue'
        review['models'][0]['columns'][0]['width'] = 120
        review['relationships'][0]['label'] = 'Customer relationship'
        review['relationships'][0]['evidence'] = 'Presentation-only reference'
        self.assertEqual(consistency.compare_review(design, review)['findings'], [])

    def test_review_extra_missing_duplicate_models_and_columns_are_visible(self):
        design = candidate()
        review = consistency.project_review(design)
        review['models'][0]['columns'].append(copy.deepcopy(review['models'][0]['columns'][0]))
        review['models'][1]['id'] = 'unknown'
        review['models'].append(copy.deepcopy(review['models'][0]))
        report = consistency.compare_review(design, review)
        self.assertTrue({'review_model_missing', 'review_model_extra', 'review_model_duplicate',
                         'review_column_duplicate'} <= codes(report))

    def test_review_cannot_add_structural_claims_to_unknown_relationship(self):
        design = candidate()
        review = consistency.project_review(design)
        review['relationships'][0]['from_columns'] = ['orders_id']
        review['relationships'][0]['to_columns'] = ['customers_id']
        self.assertIn('review_relationships_mismatch', codes(consistency.compare_review(design, review)))

    def test_reconcile_deduplicates_identity_and_preserves_explicit_unknown(self):
        first = candidate()
        second = copy.deepcopy(first)
        first['entities'][0]['grain'] = 'UNKNOWN'
        second['entities'][0]['grain'] = 'One row per customer'
        result = consistency.reconcile_proposals([first, second])
        self.assertEqual(result['status'], 'reconciled')
        self.assertEqual(len(result['design']['entities']), 2)
        self.assertEqual(result['design']['entities'][0]['grain'], 'UNKNOWN')
        self.assertIn('proposal_unknown_preserved', codes(result, 'unknowns'))

    def test_reconcile_refuses_contradictory_grain_or_join_claims_without_mutation(self):
        first = candidate()
        second = copy.deepcopy(first)
        second['entities'][0]['grain'] = 'One row per household'
        before = copy.deepcopy(first)
        result = consistency.reconcile_proposals([first, second])
        self.assertEqual(result['status'], 'conflicts')
        self.assertIsNone(result['design'])
        self.assertIn('proposal_conflict', codes(result))
        self.assertEqual(first, before)
        second = copy.deepcopy(first)
        second['relationships'][0]['cardinality'] = 'one_to_many'
        self.assertEqual(consistency.reconcile_proposals([first, second])['status'], 'conflicts')

    def test_reconcile_preserves_unknown_column_type_without_concatenating_columns(self):
        first = candidate()
        second = copy.deepcopy(first)
        first['entities'][0]['columns'][0]['type'] = 'UNKNOWN'
        result = consistency.reconcile_proposals([first, second])
        self.assertEqual(result['status'], 'reconciled')
        self.assertEqual(result['design']['entities'][0]['columns'][0]['type'], 'UNKNOWN')
        second['entities'][0]['columns'].append({'name': 'new_name', 'type': 'integer'})
        self.assertEqual(consistency.reconcile_proposals([first, second])['status'], 'conflicts')

    def test_malformed_scalar_metadata_and_json_duplicate_keys_are_bounded(self):
        design = candidate()
        design['entities'][0]['layer'] = ['not', 'a', 'layer']
        design['relationships'][0].update(cardinality={}, from_columns=['orders_id'], to_columns=['customers_id'])
        self.assertIn('invalid_model_layer', codes(consistency.assess_design(design)))
        with self.assertRaisesRegex(ValueError, 'Duplicate JSON'):
            consistency.assess_design('{"schema_version":1,"schema_version":2}')
        with self.assertRaises(ValueError):
            consistency.assess_design('{"schema_version":1,"value":NaN}')

    def test_reconcile_does_not_discard_malformed_proposal_collections(self):
        first = candidate()
        second = copy.deepcopy(first)
        second['entities'] = 'not an entity inventory'
        result = consistency.reconcile_proposals([first, second])
        self.assertEqual(result['status'], 'conflicts')
        self.assertIn('invalid_collection', codes(result))

    def test_malformed_and_oversized_collections_report_without_running_inputs(self):
        design = candidate()
        design['entities'][0]['depends_on'] = {'execute': 'never'}
        self.assertIn('invalid_dependency_list', codes(consistency.assess_design(design)))
        with self.assertRaises(ValueError):
            consistency.assess_design('__import__("os").system("false")')
        with self.assertRaises(ValueError):
            consistency.assess_design({'entities': [None] * (consistency.MAX_ITEMS + 1)})


if __name__ == '__main__':
    unittest.main()
