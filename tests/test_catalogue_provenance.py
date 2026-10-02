"""Synthetic normalized/export mappings; no warehouse provenance is asserted."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'
sys.path.insert(0, str(SCRIPTS))
import test_catalogue as fixtures
from ae_common import hash_file, load_json
from verify_catalogue_provenance import ORIGINS, pointer, verify


def save(path, value):
    path.write_text(json.dumps(value), encoding='utf-8')


def build_provenance(catalogue_path):
    """Return (without writing) a contract for test_catalogue's exported arrays.

    Reusable by engagement tests. It selects exact matching fixture object rows
    and column paths, not an inferred vendor export format or authenticity check.
    """
    catalogue_path = Path(catalogue_path)
    catalogue = load_json(catalogue_path)
    mappings = []
    for object_index, obj in enumerate(catalogue['objects']):
        base = '/objects/' + str(object_index)
        selected = {}
        for component in ('objects', 'columns'):
            candidates = [item for item in catalogue['extractions']
                          if item['scope_id'] == obj['scope_id'] and item['component'] == component]
            if len(candidates) != 1:
                raise ValueError('Fixture requires one extraction per scope/component')
            extraction = candidates[0]
            selected[component] = (extraction['extraction_id'],
                                   load_json(catalogue_path.parent / extraction['artifact_path']))
        extraction_id, rows = selected['objects']
        indexes = [index for index, row in enumerate(rows)
                   if all(row[name] == obj['identity'][name] for name in ('catalog', 'schema', 'name'))]
        if len(indexes) != 1:
            raise ValueError('Fixture object export does not have one matching row')
        for name in ('catalog', 'schema', 'name', 'object_type'):
            target = base + ('/' if name == 'object_type' else '/identity/') + name
            mappings.append({'catalogue_pointer': target, 'extraction_id': extraction_id,
                             'export_pointer': '/' + str(indexes[0]) + '/' + name})
        extraction_id, rows = selected['columns']
        for column_index, column in enumerate(obj['columns']):
            indexes = [index for index, row in enumerate(rows)
                       if row['object'] == obj['identity']['name'] and row['path'] == column['path']]
            if len(indexes) != 1:
                raise ValueError('Fixture column export does not have one matching row')
            for name in ('path', 'data_type', 'nullable'):
                mappings.append({'catalogue_pointer': base + '/columns/' + str(column_index) + '/' + name,
                                 'extraction_id': extraction_id,
                                 'export_pointer': '/' + str(indexes[0]) + '/' + name})
    return {'schema_version': 1, 'kind': 'catalogue_provenance',
            'catalogue_sha256': hash_file(catalogue_path),
            'capture_method': next(method for method, origin in ORIGINS.items() if origin == catalogue['origin']),
            'provenance_reference': 'Synthetic test fixture exports; no live collection', 'mappings': mappings}


class CatalogueProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.catalogue_path, _ = fixtures.make_fixture(self.root)
        self.catalogue = load_json(self.catalogue_path)
        self.contract = build_provenance(self.catalogue_path)
        self.path = self.root / 'provenance.json'

    def check(self):
        save(self.path, self.contract)
        return verify(self.path, self.catalogue_path)

    def repin_catalogue(self):
        save(self.catalogue_path, self.catalogue)
        self.contract['catalogue_sha256'] = hash_file(self.catalogue_path)

    def export_path(self, component='columns'):
        return self.root / next(item['artifact_path'] for item in self.catalogue['extractions'] if item['component'] == component)

    def repin_export(self, component='columns'):
        next(item for item in self.catalogue['extractions'] if item['component'] == component)['sha256'] = hash_file(self.export_path(component))
        self.repin_catalogue()

    def test_complete_mapping_checks_all_normalized_fields(self):
        result = self.check()
        self.assertTrue(result['passed'], result)
        self.assertEqual(result['mapped_fields'], 10)
        self.assertEqual(result['catalogue_sha256'], hash_file(self.catalogue_path))
        self.assertEqual(result['capture_method'], 'synthetic_generator')
        self.assertEqual(result['origin'], 'synthetic')
        self.assertEqual(result['errors'], [])
        self.assertIn('not authenticated', ' '.join(result['limitations']))

    def test_capture_method_and_origin_must_match_exactly(self):
        for method, origin in ORIGINS.items():
            with self.subTest(method=method):
                self.catalogue['origin'] = origin
                self.repin_catalogue()
                self.contract['capture_method'] = method
                self.assertTrue(self.check()['passed'])
                self.contract['capture_method'] = next(other for other in ORIGINS if other != method)
                with self.assertRaisesRegex(ValueError, 'origin differ'):
                    self.check()

    def test_stale_catalogue_or_export_bytes_rejected(self):
        self.catalogue_path.write_bytes(self.catalogue_path.read_bytes() + b'\n')
        with self.assertRaisesRegex(ValueError, 'hash changed'):
            self.check()
        self.repin_catalogue()
        path = self.export_path()
        path.write_bytes(path.read_bytes() + b'\n')
        with self.assertRaisesRegex(ValueError, 'hash changed'):
            self.check()

    def test_rehashed_normalized_field_changes_still_fail_against_exports(self):
        original = copy.deepcopy(self.catalogue)
        mutations = [lambda o: o['identity'].update(name='Different'),
                     lambda o: o.update(object_type='VIEW'),
                     lambda o: o['columns'][0].update(path=['Wrong']),
                     lambda o: o['columns'][0].update(data_type='NUMBER'),
                     lambda o: o['columns'][0].update(nullable=True)]
        for mutate in mutations:
            self.catalogue = copy.deepcopy(original)
            mutate(self.catalogue['objects'][0])
            self.repin_catalogue()
            with self.subTest(mutate=mutate):
                result = self.check()
                self.assertFalse(result['passed'], result)
                self.assertEqual(len(result['errors']), 1)

    def test_rehashed_export_value_change_is_not_merely_hash_validation(self):
        path = self.export_path()
        rows = load_json(path)
        rows[0]['data_type'] = 'INTEGER'
        save(path, rows)
        self.repin_export()
        result = self.check()
        self.assertFalse(result['passed'])
        self.assertIn('/columns/0/data_type', result['errors'][0])

    def test_null_boolean_and_integer_are_not_coerced(self):
        path = self.export_path()
        original = load_json(path)
        for value in (0, None, 'false'):
            rows = copy.deepcopy(original)
            rows[0]['nullable'] = value
            save(path, rows)
            self.repin_export()
            with self.subTest(value=value):
                self.assertFalse(self.check()['passed'])

    def test_missing_extra_and_duplicate_mapping_targets_rejected(self):
        original = copy.deepcopy(self.contract)
        for mode in ('missing', 'duplicate', 'extra'):
            self.contract = copy.deepcopy(original)
            if mode == 'missing':
                self.contract['mappings'].pop()
            elif mode == 'duplicate':
                self.contract['mappings'].append(copy.deepcopy(self.contract['mappings'][0]))
            else:
                self.contract['mappings'][0]['catalogue_pointer'] = '/provider'
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                self.check()

    def test_unknown_or_duplicate_extraction_ids_rejected(self):
        self.contract['mappings'][0]['extraction_id'] = 'unknown'
        with self.assertRaisesRegex(ValueError, 'unknown extraction'):
            self.check()
        self.contract = build_provenance(self.catalogue_path)
        self.catalogue['extractions'].append(copy.deepcopy(self.catalogue['extractions'][0]))
        self.repin_catalogue()
        with self.assertRaisesRegex(ValueError, 'Duplicate extraction'):
            self.check()

    def test_escaped_object_keys_and_export_objects_are_supported(self):
        for component in ('objects', 'columns'):
            path = self.export_path(component)
            save(path, {'metadata/rows': {'values~raw': load_json(path)}})
            self.repin_export(component)
        for mapping in self.contract['mappings']:
            mapping['export_pointer'] = '/metadata~1rows/values~0raw' + mapping['export_pointer']
        self.assertTrue(self.check()['passed'])
        self.assertEqual(pointer({'~1': {'': 7}}, '/~01/'), 7)
        self.assertEqual(pointer([1, 2], ''), [1, 2])
        self.assertEqual(pointer({'01': 'literal map key'}, '/01'), 'literal map key')

    def test_malformed_missing_wildcard_and_unbounded_pointers_rejected(self):
        original = copy.deepcopy(self.contract)
        for value in ('0/catalog', '/-1/catalog', '/01/catalog', '/-/catalog', '/1/catalog',
                      '/*/catalog', '/0/?', '/0/missing', '/0/catalog/child', '/0/~2',
                      '/0/~', '/' + 'x' * 4096, '/' * 129, '/0/\n'):
            self.contract = copy.deepcopy(original)
            self.contract['mappings'][0]['export_pointer'] = value
            with self.subTest(pointer=value), self.assertRaises(ValueError):
                self.check()

    def test_empty_object_or_column_denominator_rejected(self):
        original = copy.deepcopy(self.catalogue)
        for mode in ('objects', 'columns'):
            self.catalogue = copy.deepcopy(original)
            if mode == 'objects':
                self.catalogue['objects'] = []
            else:
                self.catalogue['objects'][0]['columns'] = []
            self.repin_catalogue()
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, 'nonempty'):
                self.check()

    def test_malformed_catalogue_root_and_normalized_types_rejected(self):
        original = copy.deepcopy(self.catalogue)
        for value in ([], None, True):
            save(self.catalogue_path, value)
            self.contract['catalogue_sha256'] = hash_file(self.catalogue_path)
            with self.subTest(root=value), self.assertRaisesRegex(ValueError, 'catalogue schema'):
                self.check()
        mutations = [lambda c: c.update(schema_version=True),
                     lambda c: c['objects'][0]['columns'][0].update(nullable=0),
                     lambda c: c['objects'][0]['columns'][0].update(path='InvoiceId'),
                     lambda c: c['objects'][0]['identity'].pop('catalog')]
        for mutate in mutations:
            self.catalogue = copy.deepcopy(original)
            mutate(self.catalogue)
            self.repin_catalogue()
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                self.check()

    def test_strict_contract_fields_and_types(self):
        original = copy.deepcopy(self.contract)
        mutations = [lambda c: c.update(schema_version=True), lambda c: c.update(kind='wrong'),
                     lambda c: c.update(extra='typo'), lambda c: c.update(capture_method='connector'),
                     lambda c: c.update(provenance_reference=' '),
                     lambda c: c.update(provenance_reference='x' * 4097),
                     lambda c: c['mappings'][0].update(extra='typo'), lambda c: c.update(mappings=[])]
        for mutate in mutations:
            self.contract = copy.deepcopy(original)
            mutate(self.contract)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                self.check()

    def test_export_escape_and_symlink_paths_rejected(self):
        original = copy.deepcopy(self.catalogue)
        for value in ('../outside.json', str(self.export_path('objects')), 'exports/./objects.json'):
            self.catalogue = copy.deepcopy(original)
            self.catalogue['extractions'][0]['artifact_path'] = value
            self.repin_catalogue()
            with self.subTest(path=value), self.assertRaises(ValueError):
                self.check()
        self.catalogue = original
        link = self.root / 'linked-objects.json'
        link.symlink_to(self.export_path('objects'))
        self.catalogue['extractions'][0]['artifact_path'] = link.name
        self.repin_catalogue()
        with self.assertRaisesRegex(ValueError, 'Symlink'):
            self.check()

    def test_duplicate_json_keys_and_nonfinite_exports_rejected(self):
        path = self.export_path('objects')
        for body in ('[{"catalog":"Billing","catalog":"Other"}]', '[NaN]', '[Infinity]', '[1e400]'):
            path.write_text(body)
            self.repin_export('objects')
            with self.subTest(body=body), self.assertRaises(ValueError):
                self.check()
        save(self.path, self.contract)
        self.path.write_text(self.path.read_text().replace('"schema_version": 1', '"schema_version": 1, "schema_version": 1'))
        with self.assertRaisesRegex(ValueError, 'Duplicate JSON key'):
            verify(self.path, self.catalogue_path)

    def test_cli_outputs_report_and_refuses_overwrite(self):
        save(self.path, self.contract)
        output = self.root / 'report.json'
        args = [sys.executable, str(SCRIPTS / 'verify_catalogue_provenance.py'),
                '--contract', str(self.path), '--catalogue', str(self.catalogue_path), '--output', str(output)]
        first = subprocess.run(args, capture_output=True, text=True)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertTrue(load_json(output)['passed'])
        second = subprocess.run(args, capture_output=True, text=True)
        self.assertEqual(second.returncode, 1)


if __name__ == '__main__':
    unittest.main()
