"""Shared-contract Hex extraction; expected native facts are fixture-independent."""
import builtins
import io
import logging
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SKILL = Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator'
sys.path.insert(0, str(SKILL / 'scripts'))
from source_adapters.hex import CAPABILITY, parse
from source_adapters.registry import validate

OPTIONAL = all(importlib.util.find_spec(x) for x in ('yaml', 'jsonschema', 'sqlglot'))
FIXTURE = SKILL / 'examples/hex-omni-e2e/input/repo'
PROJECT = '5e760dfd-fdc7-5462-9807-a12f807eebc9'
COMPONENT = '8c7958a3-573b-5b81-9a0e-02de54bed99d'
SUMMARY = 'c7db64be-6671-54f8-8714-2d80116373e6'
PYTHON = '019ca33f-6110-5123-8c28-0b8fbb312f3f'


def fixture():
    return {str(p.relative_to(FIXTURE)): p.read_text() for p in sorted(FIXTURE.rglob('*')) if p.is_file()}


def modify(files, path, update):
    import yaml
    value = yaml.safe_load(files[path])
    update(value)
    files[path] = yaml.safe_dump(value, sort_keys=False)


@unittest.skipUnless(OPTIONAL, 'Pinned Hex parser dependencies are required')
class HexAdapterTests(unittest.TestCase):
    def codes(self, result):
        return {gap['code'] for gap in result['gaps']}

    def test_reuses_inspector_and_binds_three_projects_component_and_cell_ids(self):
        import hex_source
        files = fixture()
        with patch('hex_source.inspect_repo', wraps=hex_source.inspect_repo) as reused:
            result = parse(files)
        reused.assert_called_once()
        self.assertFalse(Path(reused.call_args.args[0]).exists())
        validate(result, files)
        self.assertEqual(sum(o['kind'] == 'hex_project' for o in result['objects']), 3)
        self.assertEqual(sum(o['kind'] == 'hex_component' for o in result['objects']), 1)
        self.assertEqual(sum(o['kind'] == 'hex_cell' for o in result['objects']), 24)
        self.assertTrue({PROJECT, COMPONENT, SUMMARY, PYTHON} <= {o['native_id'] for o in result['objects']})
        self.assertEqual(result, parse(dict(reversed(list(files.items())))))
        self.assertFalse(result['execution_performed'])
        self.assertEqual(result['native_validation'], 'not_run')
        self.assertEqual(result['export_completeness'], 'not_established')

    def test_sql_python_parameters_native_order_and_layout_are_preserved(self):
        result = parse(fixture())
        summary = next(o for o in result['objects'] if o['native_id'] == SUMMARY)
        self.assertEqual(summary['details']['cell_order'], 5)
        self.assertEqual(summary['details']['analysis']['parameters'], ['end_date', 'segment', 'start_date', 'tenant'])
        source = next(e['text'] for e in result['expressions'] if e['object_id'] == summary['id'])
        self.assertIn('SUM(PAID_CENTS) / NULLIF(SUM(NET_CENTS), 0) AS payment_rate', source)
        self.assertIn('AND TENANT_ID = {{ tenant }}', source)
        python = next(o for o in result['objects'] if o['native_id'] == PYTHON)
        self.assertIn('enriched["NET_CENTS"] = enriched["AMOUNT_CENTS"] + enriched["ADJUSTMENT_CENTS"]',
                      next(e['text'] for e in result['expressions'] if e['object_id'] == python['id']))
        tenant = next(o for o in result['objects'] if o['native_id'] == 'fab3e6a7-cd82-503f-97e4-f471a205fcf3')
        self.assertEqual(tenant['details']['native_properties']['config']['defaultValue'], 'A')
        project = next(o for o in result['objects'] if o['native_id'] == PROJECT)
        self.assertEqual(project['details']['native_properties']['appLayout']['tabs'][0]['name'], 'Overview')
        self.assertTrue({'hex.execution_order_unverified', 'hex.report_interactions_unverified',
                         'hex.external_inputs_unverified', 'hex.sql_dialect_unverified'} <= self.codes(result))

    def test_component_version_warehouse_and_file_dependency_evidence(self):
        result = parse(fixture())
        component = [d for d in result['dependencies'] if d['details']['kind'] == 'component_reference']
        self.assertEqual(len(component), 3)
        self.assertEqual({d['target'] for d in component}, {COMPONENT})
        self.assertEqual({d['details']['requested_version'] for d in component}, {'48181ff3-ae9a-5717-add9-699e64214924'})
        self.assertEqual({d['details']['resolution'] for d in component}, {'supplied_version'})
        warehouse = [d for d in result['dependencies'] if d['details']['kind'] == 'warehouse_read']
        self.assertEqual({d['details']['native_evidence'] for d in warehouse},
                         {'DMA_HEX.RAW.INVOICE_CDC', 'DMA_HEX.RAW.PAYMENT_CDC', 'DMA_HEX.RAW.CUSTOMER_HISTORY'})
        file_read = next(d for d in result['dependencies'] if d['details']['kind'] == 'file_read')
        self.assertEqual(file_read['target'], 'file:adjustments.csv')
        self.assertEqual(len(file_read['details']['supplied_file_sha256']), 64)
        self.assertIn('hex.external_data_unverified', self.codes(result))
        self.assertIn('hex.component_runtime_unverified', self.codes(result))

    def test_missing_component_file_and_variable_remain_explicit_gaps(self):
        files = fixture()
        del files['shared-revenue.hex.yaml']
        result = parse(files)
        self.assertTrue({'hex.missing_component', 'hex.unbound_variable'} <= self.codes(result))
        self.assertTrue(any(d['target'] == 'enriched' and d['details']['resolution'] == 'unresolved'
                            for d in result['dependencies']))
        files = fixture(); del files['adjustments.csv']
        self.assertIn('hex.missing_file', self.codes(parse(files)))

    def test_component_version_mismatch_is_not_bound(self):
        files = fixture()
        modify(files, 'shared-revenue.hex.yaml', lambda d: d['meta'].update(sourceVersionId='22222222-2222-4222-8222-222222222222'))
        result = parse(files)
        self.assertIn('hex.component_version_mismatch', self.codes(result))
        self.assertEqual({d['details']['resolution'] for d in result['dependencies']
                          if d['details']['kind'] == 'component_reference'}, {'unresolved'})

    def test_duplicate_id_does_not_collapse_objects_or_hide_global_gaps(self):
        files = fixture(); files['copy.hex.yaml'] = files['revenue.hex.yaml']
        result = parse(files)
        validate(result, files)
        self.assertTrue({'hex.duplicate_project_id', 'hex.duplicate_cell_id'} <= self.codes(result))
        self.assertEqual(sum(o['native_id'] == SUMMARY for o in result['objects']), 2)
        self.assertEqual(len({o['id'] for o in result['objects']}), len(result['objects']))

    def test_malformed_unsafe_deep_and_new_schema_exports_fail_closed(self):
        for text in ('schemaVersion: 3\nschemaVersion: 3', 'x: &x [1]\ny: *x',
                     '!!python/object/apply:os.system ["false"]', '{bad', 'x: ' + '[' * 55 + '0' + ']' * 55):
            with self.subTest(text=text):
                result = parse({'bad.hex.yaml': text})
                self.assertEqual(result['objects'], [])
                self.assertIn('hex.yaml_invalid', self.codes(result))
                self.assertEqual(result['expressions'][0]['text'], text)
        files = fixture()
        modify(files, 'revenue.hex.yaml', lambda d: d.update(schemaVersion=4))
        self.assertIn('hex.schema_invalid', self.codes(parse(files)))

    def test_missing_schema_and_checksum_fail_without_download(self):
        import hex_source
        with tempfile.TemporaryDirectory() as tmp, \
                patch('hex_source.SCHEMA_PATH', Path(tmp) / 'missing.json'), \
                patch('urllib.request.urlopen', side_effect=AssertionError('Network')):
            result = parse(fixture())
        self.assertIn('hex.schema_unavailable', self.codes(result))
        self.assertEqual(result['objects'], [])
        with patch('hex_source.SCHEMA_SHA256', '0' * 64):
            self.assertIn('hex.schema_unavailable', self.codes(parse(fixture())))

    def test_missing_dependency_does_not_install_or_acquire(self):
        actual = builtins.__import__
        def missing(name, *args, **kwargs):
            if name == 'sqlglot':
                raise ModuleNotFoundError('sqlglot')
            return actual(name, *args, **kwargs)
        files = fixture()
        with patch('builtins.__import__', side_effect=missing):
            result = parse(files)
        validate(result, files)
        self.assertIn('hex.missing_dependency', self.codes(result))
        self.assertEqual(result['objects'], [])

    def test_dynamic_python_never_executes_and_external_paths_never_read(self):
        files = fixture()
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / 'must-not-exist'
            external = Path(tmp) / 'private.csv'; external.write_text('private')
            source = 'import pandas as pd\nopen(%r, "w").write("bad")\nx = globals()[name]\ny = pd.read_csv(%r)\n' % (str(marker), str(external))
            modify(files, 'shared-revenue.hex.yaml', lambda d: d['cells'][1]['config'].update(source=source))
            original_read = Path.read_bytes
            def bounded_read(path):
                if path == external:
                    raise AssertionError('Outside source read')
                return original_read(path)
            with patch('os.system', side_effect=AssertionError('Execution')), \
                    patch('subprocess.run', side_effect=AssertionError('Execution')), \
                    patch('socket.create_connection', side_effect=AssertionError('Network')), \
                    patch.object(Path, 'read_bytes', bounded_read):
                result = parse(files)
            self.assertFalse(marker.exists())
        self.assertTrue({'hex.dynamic_python', 'hex.missing_file'} <= self.codes(result))
        self.assertIn(source, [e['text'] for e in result['expressions']])

    def test_unsupported_language_is_preserved_without_python_interpretation(self):
        files = fixture()
        modify(files, 'revenue.hex.yaml', lambda d: d['meta'].update(codeLanguage='R'))
        result = parse(files)
        self.assertIn('hex.unsupported_language', self.codes(result))
        self.assertTrue(any(e['language'] == 'r' for e in result['expressions']))

    def test_unknown_files_and_path_collisions_cannot_claim_coverage(self):
        result = parse({'notebook.ipynb': '{}', 'arbitrary.yaml': 'foo: bar'})
        self.assertTrue(all(f['status'] == 'unsupported' for f in result['source_files']))
        files = fixture(); files['a'] = 'file'; files['a/b.txt'] = 'nested'
        with self.assertRaises(ValueError):
            parse(files)
        with self.assertRaises(ValueError):
            parse({'../escape.hex.yaml': 'schemaVersion: 3'})
        self.assertEqual(CAPABILITY['acquisition'], 'supplied_exports')

    def test_unsupported_sql_does_not_escape_into_parser_logs(self):
        files = fixture()
        def replace_sql(data):
            for cell in data['cells']:
                if cell.get('cellType') == 'SQL':
                    cell['config']['source'] = 'GRANT SENSITIVE_SENTINEL ON ALL TABLES TO role'
        modify(files, 'revenue.hex.yaml', replace_sql)
        output = io.StringIO()
        logger = logging.getLogger('sqlglot')
        handler = logging.StreamHandler(output)
        logger.addHandler(handler)
        try:
            parse(files)
        finally:
            logger.removeHandler(handler)
        self.assertNotIn('SENSITIVE_SENTINEL', output.getvalue())


if __name__ == '__main__':
    unittest.main()
