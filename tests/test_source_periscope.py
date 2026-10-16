"""Synthetic fixtures of the documented CDT Git layout; no native execution."""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'
sys.path.insert(0, str(SCRIPTS))
from source_adapters.periscope import CAPABILITY, parse

DASH = 'dashboards/revenue.' + 'a' * 32
CHART = DASH + '/daily.' + 'b' * 32
DPATH = DASH + '/revenue.yaml'
CPATH = CHART + '/daily.yaml'
SQLPATH = CHART + '/daily.sql'


def fixture():
    return {
        DPATH: 'display_name: Revenue\nconfigured_filters:\n  hidden:\n    - Tenant:\n        default:\n          - label: Demo\n            value: demo\n  visible:\n    - Date Range:\n        default: [30 days]\ndashboard_preferences:\n  settings:\n    owner: example@example.invalid\n',
        CPATH: 'display_name: Daily revenue\nchart_type: table\ndatabase_name: BigQuery\nposition: {left: 0, top: 0}\nsize: {width: 12, height: 8}\ncode_language: python3.6\nencrypted_definition: opaque_vendor_data\n',
        SQLPATH: 'SELECT [ratio(amount, total)] FROM [orders as o] WHERE [tenant_id=Tenant]\n',
        CHART + '/daily.py': 'import revenue_math\nimport pandas as pd\nperiscope.output(df)\n',
        'snippets/ratio/ratio.yaml': 'Parameters: [Numerator, Denominator]\nSettings:\n  Metadata:\n    Owner: example@example.invalid\n',
        'snippets/ratio/ratio.sql': '[Numerator] / nullif([Denominator], 0)',
        'views/orders/orders.yaml': 'Database Name: warehouse\nSettings:\n  Materialize View: true\n  Metadata:\n    Owner: example@example.invalid\n',
        'views/orders/orders.sql': 'SELECT order_id, amount FROM raw.orders',
        'custom_modules/revenue_math.py': 'def ratio(n, d):\n    return n / d\n',
    }


@unittest.skipUnless(importlib.util.find_spec('yaml'), 'PyYAML is required')
class PeriscopeSourceTests(unittest.TestCase):
    def codes(self, report):
        return {g['code'] for g in report['gaps']}

    def test_documented_layout_identity_and_declarations(self):
        report = parse(fixture())
        self.assertEqual(report, parse(dict(reversed(list(fixture().items())))))
        objects = {o['name']: o for o in report['objects']}
        self.assertEqual(objects['Revenue']['native_id'], 'a' * 32)
        self.assertEqual(objects['Daily revenue']['native_id'], 'b' * 32)
        self.assertIsNone(objects['orders']['native_id'])
        self.assertEqual(objects['Tenant']['details']['visibility'], 'hidden')
        self.assertEqual(objects['Numerator']['kind'], 'parameter')
        self.assertEqual(objects['ratio']['details']['native_configuration']['Parameters'], ['Numerator', 'Denominator'])
        self.assertTrue(any(e['details']['kind'] == 'contained_in' and e['target'] == objects['Revenue']['id'] for e in report['dependencies']))
        self.assertTrue(any(e['details']['kind'] == 'native_reference_candidate' and e['target'] == objects['ratio']['id'] for e in report['dependencies']))
        self.assertTrue(any(e['target'] == objects['revenue_math']['id'] and e['details']['resolution'] == 'candidate' for e in report['dependencies']))
        self.assertEqual({f['path'] for f in report['source_files']}, set(fixture()))
        self.assertFalse(report['execution_performed'])
        self.assertEqual(report['export_completeness'], 'not_established')
        self.assertEqual(report['native_validation'], 'not_run')
        json.dumps(report)

    def test_native_sql_and_filters_not_silently_resolved(self):
        report = parse(fixture())
        self.assertTrue({'sql.dialect_unknown', 'periscope.template_unresolved',
                         'periscope.inherited_filters_missing', 'periscope.filter_definition_missing',
                         'periscope.encrypted_definition', 'periscope.security_not_exported',
                         'periscope.export_incomplete'} <= self.codes(report))
        expressions = [e for e in report['expressions'] if e['evidence']['path'] == SQLPATH]
        self.assertTrue(any(e['text'] == fixture()[SQLPATH] and e['language'] == 'sql:unknown' for e in expressions))
        self.assertFalse(any(e['details'].get('kind') == 'reads_from' for e in report['dependencies']))
        # A connection named BigQuery is not source evidence of its SQL dialect.
        self.assertFalse(any(e['language'] == 'bigquery' for e in report['expressions']))

    def test_malformed_and_unsafe_yaml_are_retained_and_rejected(self):
        for text in ('display_name: [unclosed', 'display_name: A\ndisplay_name: B\n',
                     'display_name: &x A\nother: *x', '!!python/object/apply:os.system [touch /tmp/unused]'):
            with self.subTest(text=text):
                report = parse({DPATH: text})
                self.assertIn('periscope.invalid_yaml', self.codes(report))
                self.assertEqual(report['objects'], [])
                self.assertEqual(report['expressions'][0]['text'], text)

    def test_unknown_format_is_not_treated_as_cdt(self):
        report = parse({'dashboard.json': '{"id": 7, "sql": "select 1"}',
                        'dashboards/fake/fake.yaml': 'widgets: []',
                        'views/orders/orders.yml': 'Database Name: db',
                        '.': 'irrelevant'})
        self.assertEqual(report['objects'], [])
        self.assertTrue(all(f['status'] == 'unsupported' for f in report['source_files']))
        self.assertIn('periscope.unknown_configuration', self.codes(report))

    def test_missing_sidecars_and_parent_are_gaps(self):
        report = parse({CPATH: fixture()[CPATH]})
        self.assertTrue({'periscope.sql_missing', 'periscope.dashboard_missing'} <= self.codes(report))
        orphan = parse({SQLPATH: 'select 1'})
        self.assertIn('periscope.configuration_missing', self.codes(orphan))
        self.assertEqual(orphan['expressions'][0]['object_id'], orphan['objects'][0]['id'])

    def test_orphan_sidecars_with_dependencies_keep_valid_partial_contract(self):
        from source_adapters.registry import parse as canonical_parse
        for path, text in (('views/v/v.sql', 'select [s]'), ('views/v/v.py', 'import pandas')):
            result = canonical_parse('periscope', {path: text})
            self.assertIn('periscope.configuration_missing', self.codes(result))
            self.assertEqual(result['source_files'][0]['status'], 'partial')
            self.assertTrue(result['dependencies'])

    def test_monorepo_paths_keep_native_identity_and_full_evidence(self):
        from source_adapters.registry import parse as canonical_parse
        files = {'projects/cdt/' + p: text for p, text in fixture().items()}
        result = canonical_parse('periscope', files)
        self.assertTrue(any(o['native_id'] == 'b' * 32 for o in result['objects']))
        self.assertTrue(all(o['evidence']['path'].startswith('projects/cdt/') for o in result['objects']))
        self.assertFalse(any(g['code'] == 'periscope.configuration_missing' for g in result['gaps']))

    def test_missing_native_identity_and_required_settings(self):
        report = parse({'dashboards/new/new.yaml': 'display_name: Draft'})
        self.assertTrue({'periscope.native_id_missing', 'periscope.required_setting_missing'} <= self.codes(report))
        self.assertIsNone(report['objects'][0]['native_id'])

    def test_unknown_settings_remain_reviewable(self):
        files = fixture()
        files[CPATH] += 'future_behavior: {formula: "retain exactly"}\n'
        report = parse(files)
        chart = next(o for o in report['objects'] if o['kind'] == 'chart')
        self.assertEqual(chart['details']['native_configuration']['future_behavior'], {'formula': 'retain exactly'})
        self.assertIn('periscope.unknown_setting', self.codes(report))

    def test_python_r_and_templates_never_execute(self):
        with tempfile.TemporaryDirectory() as temp:
            sentinel = Path(temp) / 'must-not-exist'
            files = fixture()
            files[CHART + '/daily.py'] = 'from pathlib import Path\nPath(%r).write_text("executed")\n' % str(sentinel)
            files[SQLPATH] = '{{ dangerous_call() }} SELECT 1'
            files['custom_modules/evil.r'] = 'system("touch %s")\nperiscope.source("helper")' % sentinel
            files['custom_modules/helper.r'] = 'helper <- function(x) x'
            with patch('subprocess.run', side_effect=AssertionError('execution forbidden')), patch('os.system', side_effect=AssertionError('execution forbidden')):
                report = parse(files)
            self.assertFalse(sentinel.exists())
            self.assertFalse(report['execution_performed'])
            self.assertIn('periscope.template_unresolved', self.codes(report))
            self.assertTrue(any(d['details'].get('native_reference') == 'helper' and d['details']['resolution'] == 'candidate' for d in report['dependencies']))

    def test_ambiguous_template_name_never_resolves(self):
        files = fixture()
        files['snippets/orders/orders.yaml'] = files['snippets/ratio/ratio.yaml']
        files['snippets/orders/orders.sql'] = '1'
        report = parse(files)
        edge = next(d for d in report['dependencies'] if d['details'].get('native_reference') == '[orders as o]')
        self.assertEqual(edge['details']['resolution'], 'unresolved')
        self.assertEqual(edge['target'], 'orders as o')

    def test_r_sidecar_language_and_invalid_python(self):
        files = fixture()
        files['views/orders/orders.r'] = 'periscope.source("missing")'
        files['custom_modules/bad.py'] = 'not valid python ('
        report = parse(files)
        self.assertIn('periscope.code_language_missing_or_conflicting', self.codes(report))
        self.assertIn('periscope.code_parse_error', self.codes(report))
        self.assertTrue(any(e['language'] == 'r' for e in report['expressions']))

    def test_malformed_filter_and_parameter_shapes_are_gaps(self):
        files = fixture()
        files[DPATH] = 'display_name: Test\nconfigured_filters: {hidden: [wrong]}\n'
        files['snippets/ratio/ratio.yaml'] = 'Parameters: {not: a-list}'
        report = parse(files)
        self.assertTrue({'periscope.invalid_filter', 'periscope.invalid_parameters'} <= self.codes(report))

    def test_capability_does_not_claim_live_access(self):
        self.assertEqual(CAPABILITY['acquisition'], 'supplied_exports')
        self.assertIn('Unversioned', CAPABILITY['limitations'][0])
        self.assertEqual(parse({})['objects'], [])

    def test_directory_markers_are_not_unknown_objects(self):
        files = fixture()
        files['views/.gitkeep'] = ''
        report = parse(files)
        marker = next(f for f in report['source_files'] if f['path'] == 'views/.gitkeep')
        self.assertEqual(marker['status'], 'parsed')
        self.assertFalse(any(o['evidence']['path'] == 'views/.gitkeep' for o in report['objects']))

    def test_duplicate_native_token_is_exposed(self):
        files = fixture()
        other = DASH + '/copy.' + 'b' * 32 + '/copy.yaml'
        files[other] = files[CPATH].replace('Daily revenue', 'Copy')
        report = parse(files)
        self.assertIn('periscope.duplicate_native_id', self.codes(report))


if __name__ == '__main__':
    unittest.main()
