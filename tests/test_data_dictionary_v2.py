"""Dictionary migration preserves evidence without inventing governance meaning."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills/data-model-accelerator'
sys.path.insert(0, str(SKILL / 'scripts'))
from data_dictionary_v2 import migrate_dictionary, validate_dictionary
from migrate_data_dictionary import migrate_file


def canonical():
    return {'schema_version': 1, 'kind': 'data_dictionary',
            'model_inventory_sha256': 'a' * 64, 'custom': {'untouched': ['value']},
            'models': [{'model_id': 'fixture.fact_customer', 'description': 'Explicit fixture description',
                        'grain': 'One fixture event', 'columns': [{
                            'name': 'customer_id', 'description': 'Original multiline\ncustomer description',
                            'data_type': 'VARCHAR', 'nullability': 'Logically required; not verified',
                            'key_role': 'Composite identity; not a uniqueness assertion',
                            'source': 'RAW.Customer.customer_id; free text only', 'transformation': 'Pass through',
                            'units': 'Identifier', 'classification': 'Synthetic, contains PUBLIC text',
                            'validation': 'Unverified fixture test', 'custom_column': {'keep': True}}]}]}


class DictionaryV2Tests(unittest.TestCase):
    def setUp(self):
        self.legacy = canonical()
        self.value = migrate_dictionary(self.legacy)
        self.model = self.value['models'][0]
        self.column = self.model['columns'][0]

    def assert_invalid(self, value, fragment):
        self.assertTrue(any(fragment in error for error in validate_dictionary(value)), validate_dictionary(value))

    def approve(self, record):
        record['review_status'] = 'approved'
        record['provenance']['review_reference'] = 'supplied-review:001'

    def test_canonical_migration_is_valid_without_approving_unknowns(self):
        self.assertEqual(validate_dictionary(self.value), [])
        self.assertEqual(self.column['sensitivity'], 'UNKNOWN')
        self.assertEqual(self.column['sensitivity_review_status'], 'unresolved')
        self.assertEqual(self.column['key_roles'], ['UNKNOWN'])
        self.assertEqual(self.column['source_refs'], [])
        self.assertEqual(self.model['model_role'], 'UNKNOWN')
        self.assertEqual(self.model['source_systems'], [])
        self.assertIsNone(self.model['owner'])
        self.assertEqual(self.model['review_status'], 'unresolved')
        self.assertTrue(self.value['migration']['unresolved'])

    def test_migration_preserves_original_and_extensions_without_mutating_input(self):
        before = copy.deepcopy(self.legacy)
        result = migrate_dictionary(self.legacy)
        self.assertEqual(self.legacy, before)
        self.assertEqual(result['migration']['original'], before)
        self.assertEqual(result['custom'], before['custom'])
        self.assertEqual(result['models'][0]['columns'][0]['custom_column'], {'keep': True})
        self.assertEqual(result['models'][0]['columns'][0]['source'], before['models'][0]['columns'][0]['source'])
        result['migration']['original']['custom']['untouched'].append('not shared')
        self.assertEqual(self.legacy, before)

    def test_migration_is_deterministic_and_v2_copy_is_idempotent(self):
        self.assertEqual(migrate_dictionary(self.legacy), self.value)
        migrated = migrate_dictionary(self.value)
        self.assertEqual(migrated, self.value)
        self.assertIsNot(migrated, self.value)
        self.assertIsNot(migrated['models'], self.value['models'])

    def test_original_document_hash_has_explicit_canonical_contract(self):
        raw = json.dumps(self.legacy, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()
        self.assertEqual(self.value['migration']['source_document_sha256'], hashlib.sha256(raw).hexdigest())

    def test_column_ids_are_unambiguous_for_separator_and_quoted_names(self):
        self.legacy['models'][0]['model_id'] = 'a::b.#/C'
        self.legacy['models'][0]['columns'][0]['name'] = ' d.e::f/雪 '
        value = migrate_dictionary(self.legacy)
        column = value['models'][0]['columns'][0]
        self.assertEqual(json.loads(column['column_id'].removeprefix('column:')), ['a::b.#/C', ' d.e::f/雪 '])
        self.assertEqual(column['name'], ' d.e::f/雪 ')

    def test_real_rental_shape_preserves_fields_without_inferred_model_roles(self):
        path = SKILL / 'examples/dbt-rental-trial/candidate/docs/data-dictionary.json'
        original = json.loads(path.read_text())
        result = migrate_dictionary(original)
        self.assertEqual(validate_dictionary(result), [])
        self.assertIsNone(result['model_inventory_sha256'])
        self.assertEqual(result['migration']['source_shape'], 'rental_v1')
        self.assertEqual(result['migration']['original'], original)
        for old, model in zip(original['models'], result['models']):
            self.assertEqual(model['model_id'], old['id'])
            self.assertEqual(model['dbt_id'], old['dbt_id'])
            self.assertEqual(model['keys'], old['keys'])
            self.assertEqual(model['tenant_relationships'], old['tenant_relationships'])
            self.assertEqual(model['model_role'], 'UNKNOWN')
            self.assertEqual(model['review_status'], 'unresolved')
            self.assertTrue(model['description'].startswith('UNKNOWN:'))
            for old_col, column in zip(old['columns'], model['columns']):
                self.assertEqual(column['data_type'], old_col['type'])
                self.assertEqual(column['nullable'], old_col['nullable'])
                self.assertEqual(column['source'], old_col['lineage'])
                self.assertEqual(column['source_refs'], [])
                self.assertEqual(column['key_roles'], ['UNKNOWN'])

    def test_valid_structured_source_bindings_preserve_exact_components(self):
        refs = [{'object_id': 'catalogue:exact', 'column_path': ['nested.with.dot', 'Id'], 'catalogue_sha256': 'b' * 64}]
        self.legacy['models'][0]['columns'][0]['source_refs'] = refs
        result = migrate_dictionary(self.legacy)
        self.assertEqual(result['models'][0]['columns'][0]['source_refs'], refs)

    def test_invalid_structured_lineage_remains_in_original_and_unresolved(self):
        self.legacy['models'][0]['columns'][0]['source_refs'] = [{'object_id': 'unbound'}]
        result = migrate_dictionary(self.legacy)
        self.assertEqual(result['models'][0]['columns'][0]['source_refs'], [])
        self.assertEqual(result['migration']['original'], self.legacy)
        self.assertTrue(any(row['path'].endswith('/source_refs') for row in result['migration']['unresolved']))

    def test_multiple_real_key_roles_are_supported(self):
        self.column['key_roles'] = ['FOREIGN_KEY', 'GRAIN_COMPONENT']
        self.assertEqual(validate_dictionary(self.value), [])

    def test_none_and_unknown_cannot_accompany_real_roles(self):
        for roles in (['NONE', 'FOREIGN_KEY'], ['UNKNOWN', 'GRAIN_COMPONENT'], ['NONE', 'UNKNOWN'], [], ['FOREIGN_KEY', 'FOREIGN_KEY']):
            self.column['key_roles'] = roles
            self.assert_invalid(self.value, '/key_roles')

    def test_none_requires_supplied_review_evidence(self):
        self.column['key_roles'] = ['NONE']
        self.assert_invalid(self.value, 'reviewed absence')
        self.approve(self.column)
        self.assertEqual(validate_dictionary(self.value), [])

    def test_unknown_sensitivity_cannot_be_approved(self):
        self.column['sensitivity_review_status'] = 'approved'
        self.column['sensitivity_review_reference'] = 'real-review:001'
        self.assert_invalid(self.value, 'UNKNOWN sensitivity must remain unresolved')

    def test_known_sensitivity_requires_evidence_and_approval_reference(self):
        self.column['sensitivity'] = 'PUBLIC'
        self.column['sensitivity_review_status'] = 'proposed'
        self.assert_invalid(self.value, 'stated sensitivity requires evidence')
        self.column['sensitivity_evidence'] = [{'reference': 'provided-classification:001', 'sha256': 'c' * 64}]
        self.assertEqual(validate_dictionary(self.value), [])
        self.column['sensitivity_review_status'] = 'approved'
        self.assert_invalid(self.value, 'approved sensitivity requires')
        self.column['sensitivity_review_reference'] = 'supplied-decision:001'
        self.assertEqual(validate_dictionary(self.value), [])

    def test_approved_definition_requires_evidence_and_review(self):
        self.model['review_status'] = 'approved'
        self.assert_invalid(self.value, 'approved definitions require')
        self.approve(self.model)
        self.assertEqual(validate_dictionary(self.value), [])
        self.model['provenance']['evidence'] = []
        self.assert_invalid(self.value, 'approved definitions require')

    def test_empty_names_descriptions_and_legacy_text_fail(self):
        for key in ('name', 'description', 'classification', 'source', 'key_role', 'validation'):
            value = copy.deepcopy(self.value)
            value['models'][0]['columns'][0][key] = ' \n '
            self.assert_invalid(value, '/' + key)

    def test_duplicate_model_column_name_and_id_fail(self):
        self.value['models'].append(copy.deepcopy(self.model))
        self.assert_invalid(self.value, 'duplicate model identity')
        self.value['models'].pop()
        self.model['columns'].append(copy.deepcopy(self.column))
        self.assert_invalid(self.value, 'duplicate exact column name')
        self.assert_invalid(self.value, 'duplicate column identity')

    def test_duplicate_and_incomplete_source_or_evidence_refs_fail(self):
        self.column['source_refs'] = [{'object_id': 'x', 'column_path': ['a.b'], 'catalogue_sha256': 'd' * 64}] * 2
        self.assert_invalid(self.value, 'duplicate source reference')
        self.column['source_refs'] = [{'object_id': 'x', 'column_path': 'a.b', 'catalogue_sha256': 'd' * 64}]
        self.assert_invalid(self.value, 'exact column_path')
        self.model['provenance']['evidence'] *= 2
        self.assert_invalid(self.value, 'duplicate evidence')

    def test_v1_boolean_and_unknown_versions_are_not_v2(self):
        for version in (1, True, '2', 3):
            value = copy.deepcopy(self.value)
            value['schema_version'] = version
            self.assert_invalid(value, '/schema_version')
        self.assert_invalid(self.legacy, 'migrate a copy')

    def test_malformed_enums_and_records_return_errors_not_exceptions(self):
        for key in ('model_role', 'review_status', 'source_systems', 'owner', 'provenance', 'columns'):
            value = copy.deepcopy(self.value)
            value['models'][0][key] = {'invalid': True}
            self.assertTrue(validate_dictionary(value), key)
        for key in ('key_roles', 'sensitivity', 'sensitivity_review_status', 'source_refs', 'provenance', 'sensitivity_evidence'):
            value = copy.deepcopy(self.value)
            value['models'][0]['columns'][0][key] = {'invalid': True}
            self.assertTrue(validate_dictionary(value), key)
        for value in (None, [], {}, {'schema_version': 2, 'models': [None]}):
            self.assertTrue(validate_dictionary(value))

    def test_non_json_nonfinite_and_cyclic_inputs_fail_safely(self):
        for extension in (float('nan'), float('inf'), ('tuple',), {1: 'integer key'}):
            value = copy.deepcopy(self.value)
            value['extension'] = extension
            self.assertTrue(validate_dictionary(value))
            with self.assertRaises(ValueError):
                migrate_dictionary(value)
        cyclic = {}
        cyclic['self'] = cyclic
        self.assertTrue(validate_dictionary(cyclic))

    def test_unsupported_legacy_shape_and_incomplete_v1_fail(self):
        cases = [dict(self.legacy, schema_version=True), dict(self.legacy, schema_version=3),
                 dict(self.legacy, kind='another_contract'), dict(self.legacy, model_inventory_sha256=None)]
        incomplete = copy.deepcopy(self.legacy)
        del incomplete['models'][0]['columns'][0]['source']
        cases.append(incomplete)
        for value in cases:
            with self.assertRaises(ValueError):
                migrate_dictionary(value)

    def test_rental_conflicting_canonical_field_fails(self):
        value = {'schema_version': 1, 'models': [{'id': 'x', 'dbt_id': 'model.x', 'grain': 'Declared grain',
                    'columns': [{'name': 'a', 'type': 'INTEGER', 'data_type': 'VARCHAR', 'nullable': True}]}]}
        with self.assertRaisesRegex(ValueError, 'conflicting'):
            migrate_dictionary(value)

    def test_validation_does_not_mutate(self):
        before = copy.deepcopy(self.value)
        self.assertEqual(validate_dictionary(self.value), [])
        self.assertEqual(self.value, before)

    @unittest.skipUnless(importlib.util.find_spec('jsonschema'), 'Install the pinned metadata verification dependencies for JSON Schema parity')
    def test_json_schema_and_dependency_free_validator_agree_on_contract_cases(self):
        from jsonschema import Draft202012Validator
        schema = json.loads((SKILL / 'schemas/data-dictionary-v2.schema.json').read_text())
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
        self.assertFalse(list(validator.iter_errors(self.value)))
        for field, bad in [('sensitivity', 'PRIVATE'), ('key_roles', ['UNKNOWN', 'PRIMARY_KEY']),
                           ('sensitivity_review_status', 'approved'), ('column_id', ''), ('source_refs', [{'object_id': 'unbound'}])]:
            value = copy.deepcopy(self.value)
            value['models'][0]['columns'][0][field] = bad
            self.assertTrue(validate_dictionary(value), field)
            self.assertTrue(list(validator.iter_errors(value)), field)


class MigrationFileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / 'original.json'
        self.destination = self.root / 'migrated.json'
        self.raw = (json.dumps(canonical(), indent=4) + '\n').encode()
        self.source.write_bytes(self.raw)

    def test_new_file_preserves_original_bytes_and_binds_actual_byte_hash(self):
        result = migrate_file(self.source, self.destination)
        self.assertEqual(self.source.read_bytes(), self.raw)
        self.assertEqual(result['migration']['source_file_sha256'], hashlib.sha256(self.raw).hexdigest())
        self.assertEqual(json.loads(self.destination.read_text()), result)
        self.assertEqual(self.destination.stat().st_mode & 0o777, 0o600)

    def test_same_existing_hardlinked_and_symlink_outputs_are_refused(self):
        with self.assertRaises(ValueError):
            migrate_file(self.source, self.source)
        self.destination.write_text('keep existing')
        with self.assertRaises(ValueError):
            migrate_file(self.source, self.destination)
        self.assertEqual(self.destination.read_text(), 'keep existing')
        self.destination.unlink()
        os.link(self.source, self.destination)
        with self.assertRaises(ValueError):
            migrate_file(self.source, self.destination)
        self.assertEqual(self.source.read_bytes(), self.raw)
        self.destination.unlink()
        self.destination.symlink_to(self.root / 'missing.json')
        with self.assertRaises(ValueError):
            migrate_file(self.source, self.destination)

    def test_symlink_input_and_output_parent_are_refused(self):
        linked = self.root / 'linked.json'
        linked.symlink_to(self.source)
        with self.assertRaises(ValueError):
            migrate_file(linked, self.destination)
        directory = self.root / 'dir-link'
        directory.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            migrate_file(self.source, directory / 'result.json')

    def test_invalid_duplicate_and_nonfinite_json_leave_no_output(self):
        for raw in ('{"schema_version":1,"schema_version":1}', '{"value":NaN}', 'not JSON'):
            self.source.write_text(raw)
            with self.assertRaises(ValueError):
                migrate_file(self.source, self.destination)
            self.assertFalse(self.destination.exists())

    def test_cli_succeeds_once_and_never_overwrites(self):
        args = [sys.executable, str(SKILL / 'scripts/migrate_data_dictionary.py'),
                '--input', str(self.source), '--output', str(self.destination)]
        first = subprocess.run(args, capture_output=True, text=True)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertGreater(json.loads(first.stdout)['unresolved'], 0)
        before = self.destination.read_bytes()
        second = subprocess.run(args, capture_output=True, text=True)
        self.assertNotEqual(second.returncode, 0)
        self.assertEqual(self.destination.read_bytes(), before)
        self.assertEqual(self.source.read_bytes(), self.raw)


if __name__ == '__main__':
    unittest.main()
