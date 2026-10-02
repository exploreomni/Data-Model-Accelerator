"""Real six-dialect lint plus bounded coverage/security regressions; no warehouse."""
import copy
from contextlib import redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import lint_delivery as lint

PYTHON = os.environ.get('SQLFLUFF_PYTHON', sys.executable)
try:
    RUNTIME = lint.inspect_runtime(PYTHON)
except (ValueError, OSError, TimeoutError, OverflowError):
    RUNTIME = None

VALID = {
    'snowflake': 'SELECT 1::NUMBER AS id\n',
    'databricks': "SELECT named_struct('id', 1) AS payload\n",
    'bigquery': 'SELECT STRUCT(1 AS id) AS payload\n',
    'redshift': 'SELECT TOP 1 1 AS order_key\n',
    'clickhouse': 'SELECT [1, 2] AS values_list\n',
    'motherduck': "SELECT { 'id': 1 } AS payload\n",
}


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name).resolve()
        self.root = self.workspace / 'source'
        self.root.mkdir()
        self.manifest = {'schema_version': 1, 'kind': 'sql_lint_manifest',
                         'files': [], 'expected_execution_units': []}
        self.target = {'warehouse': 'snowflake', 'framework': 'native_sql', 'environment': 'fixture'}

    def add(self, path, body='SELECT 1 AS id\n', *, role='model_sql', format='sql', units=None, sources=None):
        data = body.encode() if isinstance(body, str) else body
        destination = self.root / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        units = ([path] if format in {'sql', 'compiled_sql'} else []) if units is None else units
        item = {'path': path, 'sha256': hashlib.sha256(data).hexdigest(), 'role': role, 'format': format,
                'execution_units': units, 'source_paths': sources or []}
        self.manifest['files'].append(item)
        self.manifest['expected_execution_units'].extend(units)
        return item

    def run_lint(self, **kwargs):
        return lint.lint_delivery(self.root, self.manifest, self.target, python_executable=PYTHON, **kwargs)

    def allow_style(self, path, rule, reason='Preserve the explicitly reviewed source/framework convention.'):
        self.manifest.setdefault('style_exceptions', []).append({'path': path, 'rule': rule, 'reason': reason})

    def resign(self, report):
        report['report_sha256'] = lint.hash_json({k: v for k, v in report.items() if k != 'report_sha256'})
        return report


class LintContractTests(Fixture):
    def test_style_exception_contract_rejects_nonexact_unsafe_or_duplicate_declarations(self):
        self.add('model.sql')
        self.add('settings.yml', 'name: test\n', role='project_config', format='yaml')
        self.add('source.sql', '{{ ref("example") }}', role='dbt_model', format='jinja')
        valid = {'path': 'model.sql', 'rule': 'CP02', 'reason': 'Preserve identifier case.'}
        invalid = [None, {}, [dict(valid, path='*.sql')], [dict(valid, path='../model.sql')],
                   [dict(valid, path='missing.sql')], [dict(valid, path='settings.yml')],
                   [dict(valid, path='source.sql')], [dict(valid, reason='  ')],
                   [dict(valid, reason='line\nbreak')], [dict(valid, reason=None)],
                   [dict(valid, extra=True)], [valid, valid]]
        for rule in ('PRS', 'LXR', 'TMP', 'CP03', 'RF01', 'UNKNOWN', 'cp02', 'noqa', '*'):
            invalid.append([dict(valid, rule=rule)])
        for declarations in invalid:
            changed = dict(self.manifest, style_exceptions=declarations)
            with self.subTest(declarations=declarations), self.assertRaises(ValueError):
                lint._manifest(changed, lint.DEFAULT_LIMITS)
        self.manifest['style_exceptions'] = [valid]
        indexed = lint._manifest(self.manifest, lint.DEFAULT_LIMITS)
        self.assertEqual(lint._style_exceptions(self.manifest, indexed),
                         [dict(valid, sha256=self.manifest['files'][0]['sha256'])])

    def test_exception_policy_never_converts_runtime_skipped_unsupported_or_noqa_receipts(self):
        item = self.add('model.sql')
        self.allow_style('model.sql', 'CP02')
        base = dict(item, status='failed', check_type='sql_lint', inline_noqa_count=0,
                    tool_output_sha256='a' * 64,
                    findings=[lint._finding('CP02', 'error', 'model.sql', 'Convention finding.')])
        for altered in (dict(base, reason='Runtime failed.'), dict(base, status='skipped'),
                        dict(base, status='unsupported'), dict(base, inline_noqa_count=1),
                        dict(base, tool_output_sha256=None), dict(base, check_type='yaml_structure')):
            with self.subTest(altered=altered):
                files, summary, blockers = lint._apply_style_exceptions(self.manifest, [altered])
                self.assertNotEqual(files[0]['status'], 'checked')
                self.assertEqual(summary['used_count'], 0)
                self.assertEqual(blockers[0]['code'], 'UNUSED_STYLE_EXCEPTION')

    def test_empty_missing_duplicate_or_unassigned_denominator_fails(self):
        with self.assertRaises(ValueError):
            lint._manifest(self.manifest, lint.DEFAULT_LIMITS)
        self.add('model.sql')
        for units in ([], ['missing'], ['model.sql', 'model.sql']):
            altered = dict(self.manifest, expected_execution_units=units)
            with self.subTest(units=units), self.assertRaises(ValueError):
                lint._manifest(altered, lint.DEFAULT_LIMITS)
        self.manifest['files'].append(copy.deepcopy(self.manifest['files'][0]))
        with self.assertRaises(ValueError):
            lint._manifest(self.manifest, lint.DEFAULT_LIMITS)

    def test_compiled_output_requires_hashed_declared_sources(self):
        self.add('compiled.sql', format='compiled_sql', sources=['missing.sql'])
        with self.assertRaises(ValueError):
            lint._manifest(self.manifest, lint.DEFAULT_LIMITS)
        self.manifest['files'][0]['source_paths'] = []
        with self.assertRaises(ValueError):
            lint._manifest(self.manifest, lint.DEFAULT_LIMITS)

    def test_manifest_rejects_traversal_absolute_symlink_and_role_relabeling(self):
        self.add('model.sql')
        for path in ('../model.sql', '/model.sql', 'a//model.sql', 'a\\model.sql'):
            changed = copy.deepcopy(self.manifest)
            changed['files'][0]['path'] = path
            with self.subTest(path=path), self.assertRaises(ValueError):
                lint._manifest(changed, lint.DEFAULT_LIMITS)
        (self.root / 'link.sql').symlink_to(self.root / 'model.sql')
        with self.assertRaisesRegex(ValueError, 'Symlink'):
            lint._inventory(self.root, lint.DEFAULT_LIMITS)
        self.manifest['files'][0]['role'] = 'documentation'
        with self.assertRaises(ValueError):
            lint._manifest(self.manifest, lint.DEFAULT_LIMITS)

    def test_policy_is_raw_python_parser_with_failing_skips_and_no_suppression(self):
        config = lint.configuration(self.target)
        for setting in ('templater = raw', 'disable_noqa = True', 'ignore_templated_areas = False',
                        'large_file_skip_fail = True', 'use_rust_parser = False', 'rules = all'):
            self.assertIn(setting, config)
        with self.assertRaises(ValueError):
            lint.configuration(self.target, {'max_file_bytes': 999999999})
        with self.assertRaises(ValueError):
            lint.configuration({'warehouse': 'generic-ansi-fallback'})

    def test_scaffold_counts_files_but_does_not_invent_rendered_lineage(self):
        self.add('model.sql')
        self.add('macros/example.sql', '{% macro example() %}SELECT 1{% endmacro %}', role='macro', format='jinja')
        self.add('target/compiled/output.sql')
        self.add('project.yml', 'name: fixture\n', role='project_config', format='yaml')
        proposed = lint.scaffold_manifest(self.root)
        self.assertTrue(proposed['review_required'])
        self.assertEqual(len(proposed['manifest']['files']), 4)
        self.assertEqual({p['path'] for p in proposed['unresolved_sources']}, {'macros/example.sql', 'target/compiled/output.sql'})
        with self.assertRaises(ValueError):
            lint._manifest(proposed['manifest'], lint.DEFAULT_LIMITS)

    def test_scaffold_cli_writes_only_new_external_manifest(self):
        self.add('model.sql')
        output = self.workspace / 'manifest.json'
        before = (self.root / 'model.sql').read_bytes()
        with redirect_stdout(io.StringIO()):
            self.assertEqual(lint.main(['--root', str(self.root), '--scaffold', '--output', str(output)]), 0)
        self.assertEqual(json.loads(output.read_text())['files'][0]['sha256'], hashlib.sha256(before).hexdigest())
        self.assertEqual((self.root / 'model.sql').read_bytes(), before)

    def test_native_omni_scaffold_includes_all_configuration_files(self):
        self.add('model.sql')
        for path in ('omni/model', 'omni/relationships', 'omni/orders.view', 'omni/orders.topic'):
            self.add(path, 'ai_context: Provisional\n', role='semantic_config', format='yaml', units=[])
        proposed = lint.scaffold_manifest(self.root)
        semantic = [f for f in proposed['manifest']['files'] if f['path'].startswith('omni/')]
        self.assertEqual(len(semantic), 4)
        self.assertTrue(all(f['role'] == 'semantic_config' and f['format'] == 'yaml' for f in semantic))
        self.assertEqual(proposed['unresolved_sources'], [])

    def test_modeling_review_is_separate_from_lint_and_key_truth(self):
        self.add('model.sql')
        self.manifest['physical_models'] = [{'id': 'gold.orders', 'path': 'model.sql', 'engine': 'ReplacingMergeTree'}]
        codes = {f['code'] for f in lint.modeling_findings(self.manifest, {'warehouse': 'clickhouse'})}
        self.assertTrue({'CLICKHOUSE_UNIQUENESS', 'CLICKHOUSE_ORDER_KEY', 'MODEL_GRAIN', 'MODEL_KEYS'} <= codes)
        codes = {f['code'] for f in lint.modeling_findings(self.manifest, {'warehouse': 'redshift'})}
        self.assertTrue({'REDSHIFT_INFORMATIONAL_KEYS', 'REDSHIFT_DISTRIBUTION', 'REDSHIFT_SORT_STRATEGY'} <= codes)
        self.assertIn('MOTHERDUCK_REMOTE_BINDING', {f['code'] for f in lint.modeling_findings(self.manifest, {'warehouse': 'motherduck'})})

    def test_child_environment_excludes_credentials_pythonpath_and_config(self):
        with patch.dict(os.environ, {'DBT_PROFILES_DIR': '/secret', 'WAREHOUSE_TOKEN': 'private',
                                   'PYTHONPATH': '/untrusted', 'SQLFLUFF_CONFIG': '/untrusted'}):
            code, out, _ = lint._run(sys.executable, ['-c', 'import os,json; print(json.dumps(dict(os.environ)))'],
                                    self.workspace, 5, 10000)
        self.assertEqual(code, 0)
        observed = json.loads(out)
        for key in ('DBT_PROFILES_DIR', 'WAREHOUSE_TOKEN', 'PYTHONPATH', 'SQLFLUFF_CONFIG'):
            self.assertNotIn(key, observed)

    def test_real_child_timeout_and_output_bounds_fail_closed(self):
        with self.assertRaises(TimeoutError):
            lint._run(sys.executable, ['-c', 'import time; time.sleep(3)'], self.workspace, 0.1, 10000)
        with self.assertRaises((ValueError, OverflowError)):
            lint._run(sys.executable, ['-c', 'print("x" * 100000)'], self.workspace, 5, 1024)

    def test_runtime_rejects_wrong_version_and_third_party_lint_plugins(self):
        observations = [
            {'sqlfluff_version': '4.2.1'},
            {'sqlfluff_version': '4.3.0', 'sqlfluff_files': [['core.py', 'a' * 64]],
             'plugins': [['third-party-plugin', 'unsafe', 'untrusted:code']], 'packages': []},
        ]
        for observed in observations:
            with self.subTest(observed=observed['sqlfluff_version']), patch.object(lint, '_run',
                    return_value=(0, json.dumps(observed).encode(), b'')), self.assertRaises(ValueError):
                lint.inspect_runtime(sys.executable)


@unittest.skipUnless(RUNTIME, 'Install requirements-lint.txt in a trusted runtime or set SQLFLUFF_PYTHON')
class RealLintTests(Fixture):
    CASE_SQL = 'SELECT\n    customerID,\n    customer_id\nFROM source_data\n'
    ORDER_SQL = 'SELECT\n    a + 1 AS derived,\n    a\nFROM source_data\n'

    def test_exact_style_policy_passes_with_raw_findings_hashes_reasons_and_replay(self):
        case = self.add('case.sql', self.CASE_SQL)
        self.add('order.sql', self.ORDER_SQL)
        self.assertEqual(self.run_lint()['status'], 'failed')
        self.allow_style('order.sql', 'ST06', ' Preserve the contract projection order. ')
        self.allow_style('case.sql', 'CP02', 'Preserve framework-generated identifier case.')
        report = self.run_lint()
        self.assertEqual(report['status'], 'passed', report['files'])
        summary = report['style_exceptions']
        self.assertEqual((summary['declared_count'], summary['used_count'], summary['unused_count']), (2, 2, 0))
        self.assertEqual(summary['files_converted_to_checked'], 2)
        self.assertEqual(summary['declarations'][0]['sha256'], case['sha256'])
        self.assertEqual(summary['declarations'][1]['reason'], 'Preserve the contract projection order.')
        self.assertFalse(summary['human_approval'])
        for file in report['files']:
            self.assertEqual((file['raw_status'], file['status']), ('failed', 'checked'))
            self.assertTrue(file['findings'])
            self.assertTrue(all(f['severity'] == 'error' for f in file['findings']))
            self.assertTrue(file['style_exception_applications'])
        verified = lint.verify_report(report, self.root, self.target, self.manifest, runtime=RUNTIME)
        self.assertEqual(verified['style_exceptions'], summary)
        self.assertFalse(verified['native_verified'])
        self.assertEqual((self.root / 'case.sql').read_text(), self.CASE_SQL)

    def test_style_exception_does_not_hide_parser_noqa_inline_config_or_template_failures(self):
        cases = [
            ('SELECT\n    customerID,\n    customer_id\nFROM\n', 'PRS'),
            (self.CASE_SQL + '-- noqa: CP02\n', None),
            ('-- sqlfluff:rules:CP02\n' + self.CASE_SQL, None),
            ("SELECT {{ ref('source') }} AS customerID\n", None),
        ]
        for sql, expected_code in cases:
            with self.subTest(sql=sql):
                self.manifest['files'] = []; self.manifest['expected_execution_units'] = []
                self.manifest['style_exceptions'] = []
                self.add('model.sql', sql)
                self.allow_style('model.sql', 'CP02')
                report = self.run_lint()
                self.assertEqual(report['status'], 'failed')
                self.assertNotEqual(report['files'][0]['status'], 'checked')
                if expected_code:
                    self.assertIn(expected_code, {f['code'] for f in report['files'][0]['findings']})
                with self.assertRaises(ValueError):
                    lint.verify_report(report, self.root)

    def test_unused_wrong_scope_and_stale_rule_exceptions_fail(self):
        self.add('case.sql', self.CASE_SQL)
        self.add('plain.sql')
        for path, rule in [('plain.sql', 'CP02'), ('case.sql', 'ST06')]:
            with self.subTest(path=path, rule=rule):
                self.manifest['style_exceptions'] = []
                self.allow_style(path, rule)
                report = self.run_lint()
                self.assertEqual(report['status'], 'failed')
                self.assertEqual(report['style_exceptions']['unused_count'], 1)
                self.assertTrue(any(f['code'] == 'UNUSED_STYLE_EXCEPTION' for f in report['findings']))
        # Even otherwise clean SQL cannot pass with an obsolete declaration.
        (self.root / 'case.sql').write_text('SELECT 1 AS id\n')
        self.manifest['files'][0]['sha256'] = hashlib.sha256((self.root / 'case.sql').read_bytes()).hexdigest()
        self.manifest['style_exceptions'] = []
        self.allow_style('case.sql', 'CP02')
        report = self.run_lint()
        self.assertTrue(all(f['status'] == 'checked' for f in report['files']))
        self.assertEqual(report['status'], 'failed')
        self.assertFalse(report['coverage']['complete'])

    def test_exception_cannot_survive_source_drift_or_manifest_policy_changes(self):
        self.add('case.sql', self.CASE_SQL)
        self.allow_style('case.sql', 'CP02')
        report = self.run_lint()
        changed = copy.deepcopy(self.manifest)
        changed['style_exceptions'][0]['reason'] = 'A different policy.'
        with self.assertRaisesRegex(ValueError, 'manifest drift'):
            lint.verify_report(report, self.root, manifest=changed)
        (self.root / 'case.sql').write_text(self.CASE_SQL + '-- changed\n')
        with self.assertRaisesRegex(ValueError, 'content drift'):
            lint.verify_report(report, self.root)
        fresh = self.run_lint()
        self.assertEqual(fresh['status'], 'failed')
        self.assertEqual(fresh['style_exceptions']['used_count'], 0)

    def test_report_reverification_rejects_forged_exception_conversion(self):
        self.add('case.sql', self.CASE_SQL)
        self.allow_style('case.sql', 'CP02')
        original = self.run_lint()
        mutations = [
            lambda r: r['style_exceptions'].update(excepted_finding_count=0),
            lambda r: r['style_exceptions']['declarations'][0].update(reason='Invented reason'),
            lambda r: r['style_exceptions']['applications'][0].update(sha256='f' * 64),
            lambda r: r['files'][0]['style_exception_applications'][0].update(finding_indices=[]),
            lambda r: r['files'][0].update(raw_status='checked'),
            lambda r: r['files'][0].pop('raw_status'),
            lambda r: r.pop('style_exceptions'),
            lambda r: r['files'][0]['findings'].append(lint._finding('PRS', 'error', 'case.sql', 'Parse failure.')),
            lambda r: r['files'][0].update(reason='SQLFluff runtime failed.'),
        ]
        for mutate in mutations:
            changed = copy.deepcopy(original); mutate(changed); self.resign(changed)
            with self.subTest(mutation=mutations.index(mutate)), self.assertRaises(ValueError):
                lint.verify_report(changed, self.root)

    def test_verifier_recomputes_noqa_boundary_from_pinned_source(self):
        self.add('case.sql', self.CASE_SQL + '-- noqa: CP02\n')
        self.allow_style('case.sql', 'CP02')
        report = self.run_lint()
        self.assertEqual(report['status'], 'failed')
        # Forge a internally consistent conversion while hiding the source marker.
        report['files'][0]['inline_noqa_count'] = 0
        report['files'], report['style_exceptions'], _ = lint._apply_style_exceptions(self.manifest, report['files'])
        report['coverage'], report['execution_units'] = lint._coverage(self.manifest, report['files'])
        report.update(status='passed', findings=[])
        self.resign(report)
        with self.assertRaisesRegex(ValueError, 'noqa'):
            lint.verify_report(report, self.root)

    def test_pre_exception_strict_reports_remain_verifiable(self):
        self.add('model.sql')
        report = self.run_lint()
        report.pop('style_exceptions')
        for item in report['files']:
            item.pop('raw_status'); item.pop('style_exception_applications')
        self.resign(report)
        self.assertEqual(lint.verify_report(report, self.root)['status'], 'verified')

    def test_real_valid_and_invalid_sql_in_all_six_dialects(self):
        for warehouse, sql in VALID.items():
            with self.subTest(warehouse=warehouse):
                self.target['warehouse'] = warehouse
                self.manifest['files'] = []; self.manifest['expected_execution_units'] = []
                self.add('valid.sql', sql)
                self.add('invalid.sql', 'SELEC 1 AS id\n')
                before = {p.name: p.read_bytes() for p in self.root.iterdir()}
                report = self.run_lint()
                by_path = {f['path']: f for f in report['files']}
                self.assertEqual(by_path['valid.sql']['status'], 'checked', by_path['valid.sql'])
                self.assertEqual(by_path['invalid.sql']['status'], 'failed')
                self.assertTrue(any(f['code'] == 'PRS' for f in by_path['invalid.sql']['findings']))
                self.assertEqual(report['coverage']['execution_units']['expected'], 2)
                self.assertEqual(report['coverage']['execution_units']['checked'], 1)
                self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir()})
                with self.assertRaises(ValueError):
                    lint.verify_report(report, self.root)

    def test_plain_success_reverification_and_no_authority(self):
        self.add('model.sql')
        report = self.run_lint()
        self.assertEqual(report['status'], 'passed', report['files'])
        verified = lint.verify_report(report, self.root, self.target, self.manifest, runtime=RUNTIME)
        self.assertTrue(verified['runtime_reverified'])
        self.assertFalse(verified['native_verified'])
        self.assertFalse(verified['business_approved'])
        self.assertFalse(verified['execution_authorized'])

    def test_noqa_and_hostile_ambient_configuration_do_not_suppress_errors(self):
        self.add('bad.sql', 'SELEC 1 AS id -- noqa: PRS\n')
        (self.root / '.sqlfluff').write_text('[sqlfluff]\ntemplater = python\nignore = parsing\n')
        (self.root / '.sqlfluffignore').write_text('*.sql\n')
        report = self.run_lint()
        self.assertEqual(report['status'], 'failed')
        self.assertEqual(report['files'][0]['inline_noqa_count'], 1)
        self.assertEqual(len(report['inventory']['ignored_configuration']), 2)
        self.assertTrue(report['files'][0]['findings'])

    def test_style_findings_are_not_misreported_as_invalid_vendor_syntax(self):
        self.target['warehouse'] = 'clickhouse'
        self.add('native_function.sql', 'SELECT arrayJoin([1, 2]) AS order_key\n')
        report = self.run_lint()
        codes = {f['code'] for f in report['files'][0]['findings']}
        self.assertIn('CP03', codes)
        self.assertNotIn('PRS', codes)
        self.assertEqual(report['status'], 'failed')
        # No automatic capitalization fix: ClickHouse function case is semantic.
        self.assertIn('arrayJoin', (self.root / 'native_function.sql').read_text())

    def test_inline_configuration_unrendered_template_and_unmapped_macro_are_visible(self):
        self.add('plain.sql')
        self.add('inline.sql', '-- sqlfluff:dialect:ansi\nSELECT 1 AS id\n')
        self.add('unrendered.sql', "SELECT * FROM {{ ref('orders') }}\n")
        self.add('macros/unmapped.sql', '{% macro x() %}SELECT 1{% endmacro %}', role='macro', format='jinja')
        report = self.run_lint()
        self.assertEqual(report['status'], 'failed')
        self.assertEqual(report['coverage']['files']['unsupported'], 3)
        self.assertEqual(report['coverage']['execution_units']['unsupported'], 2)

    def test_generated_hook_and_model_map_all_source_files(self):
        self.add('models/source.sql', "SELECT {{ var('value') }} AS id", role='dbt_model', format='jinja')
        self.add('macros/value.sql', '{% macro value() %}1{% endmacro %}', role='macro', format='jinja')
        self.add('hooks/pre.sql', "SELECT {{ var('value') }} AS id", role='hook_template', format='jinja')
        self.add('compiled/model.sql', format='compiled_sql', units=['model:orders'],
                 sources=['models/source.sql', 'macros/value.sql'])
        self.add('compiled/hook.sql', format='compiled_sql', role='hook_sql', units=['hook:orders:pre'], sources=['hooks/pre.sql'])
        report = self.run_lint()
        self.assertEqual(report['status'], 'passed', report['files'])
        self.assertEqual(report['coverage']['files']['expected'], 5)
        self.assertEqual(report['coverage']['execution_units']['checked'], 2)
        self.assertEqual([f['check_type'] for f in report['files'][:3]], ['source_mapping'] * 3)

    def test_missing_undeclared_added_and_changed_inputs_cannot_pass(self):
        self.add('model.sql')
        (self.root / 'hidden_hook.sql').write_text('SELECT 2 AS id\n')
        report = self.run_lint()
        self.assertEqual(report['status'], 'failed')
        self.assertEqual(report['findings'][0]['code'], 'UNDECLARED_INPUT')
        (self.root / 'hidden_hook.sql').unlink()
        report = self.run_lint()
        (self.root / 'model.sql').write_text('SELECT 2 AS id\n')
        with self.assertRaises(ValueError):
            lint.verify_report(report, self.root)
        self.assertEqual(self.run_lint()['status'], 'failed')

    def test_large_file_above_vendor_default_is_checked_then_explicit_bounds_fail(self):
        self.add('large.sql', '-- padding\n' * 2200 + 'SELECT 1 AS id\n')
        report = self.run_lint()
        self.assertEqual(report['status'], 'passed', report['files'])
        bounded = self.run_lint(limits={'max_file_bytes': 10000})
        self.assertEqual(bounded['files'][0]['status'], 'skipped')
        self.assertFalse(bounded['coverage']['complete'])

    def test_empty_invalid_encoding_and_comment_only_sql_are_not_execution(self):
        self.add('empty.sql', '')
        self.add('comment.sql', '-- only a comment\n')
        self.add('binary.sql', b'\xff\xfe')
        report = self.run_lint()
        self.assertEqual(report['coverage']['files']['failed'], 3)
        self.assertEqual(report['status'], 'failed')

    def test_json_yaml_duplicate_keys_and_yaml_aliases_are_distinct_structural_results(self):
        self.add('model.sql')
        self.add('good.json', '{"name":"fixture"}', role='project_config', format='json')
        self.add('duplicate.json', '{"name":1,"name":2}', role='project_config', format='json')
        self.add('good.yaml', 'name: fixture\n', role='project_config', format='yaml')
        self.add('duplicate.yaml', 'name: first\nname: second\n', role='project_config', format='yaml')
        self.add('alias.yaml', 'name: &base fixture\nother: *base\n', role='project_config', format='yaml')
        report = self.run_lint()
        statuses = {f['path']: f['status'] for f in report['files']}
        self.assertEqual(statuses, {'model.sql': 'checked', 'good.json': 'checked', 'duplicate.json': 'failed',
                                  'good.yaml': 'checked', 'duplicate.yaml': 'failed', 'alias.yaml': 'unsupported'})

    def test_unregistered_and_malformed_native_omni_config_cannot_escape_lint(self):
        self.add('model.sql')
        (self.root / 'omni').mkdir()
        (self.root / 'omni/model').write_text('ai_context: first\nai_context: second\n')
        report = self.run_lint()
        self.assertEqual(report['status'], 'failed')
        self.assertTrue(any(f['code'] == 'UNDECLARED_INPUT' for f in report['findings']))
        self.manifest = lint.scaffold_manifest(self.root)['manifest']
        report = self.run_lint()
        result = next(f for f in report['files'] if f['path'] == 'omni/model')
        self.assertEqual(result['check_type'], 'yaml_structure')
        self.assertEqual(result['status'], 'failed')

    def test_config_target_manifest_runtime_and_report_drift_are_rejected(self):
        self.add('model.sql')
        report = self.run_lint()
        for field, value in [('configuration', report['configuration'] + 'ignore = parsing\n'),
                             ('config_sha256', 'f' * 64), ('runtime_sha256', 'f' * 64)]:
            changed = copy.deepcopy(report)
            changed[field] = value
            changed['report_sha256'] = lint.hash_json({k: v for k, v in changed.items() if k != 'report_sha256'})
            with self.subTest(field=field), self.assertRaises(ValueError):
                lint.verify_report(changed, self.root)
        with self.assertRaises(ValueError):
            lint.verify_report(report, self.root, dict(self.target, warehouse='bigquery'))
        with self.assertRaises(ValueError):
            lint.verify_report(report, self.root, runtime=dict(RUNTIME, python_version='changed'))
        changed = copy.deepcopy(self.manifest)
        changed['expected_execution_units'] = ['other']
        with self.assertRaises(ValueError):
            lint.verify_report(report, self.root, manifest=changed)

    def test_diagnostics_do_not_echo_source_literals(self):
        self.add('model.sql', "PRIVATE_SOURCE_VALUE is not SQL\n")
        report = self.run_lint()
        self.assertEqual(report['status'], 'failed')
        self.assertNotIn('PRIVATE_SOURCE_VALUE', json.dumps(report))

    def test_tool_omission_timeout_duplicate_receipt_and_unexpected_stderr_block(self):
        self.add('model.sql')
        cases = [(0, b'[]', b''), TimeoutError('fixture'),
                 (0, b'[{"filepath":"sql-0000.sql","violations":[]},{"filepath":"sql-0000.sql","violations":[]}]', b''),
                 (0, b'[{"filepath":"sql-0000.sql","violations":[]}]', b'unexpected parser warning')]
        for response in cases:
            kwargs = {'side_effect': response} if isinstance(response, Exception) else {'return_value': response}
            with self.subTest(response_type=type(response).__name__), patch.object(lint, 'inspect_runtime', return_value=RUNTIME), patch.object(lint, '_run', **kwargs):
                report = self.run_lint()
            self.assertEqual(report['status'], 'failed')
            self.assertFalse(report['coverage']['complete'])

    def test_zero_findings_does_not_prove_metric_value(self):
        self.add('wrong_metric.sql', 'SELECT 999 AS revenue\n')
        report = self.run_lint()
        self.assertEqual(report['status'], 'passed')
        self.assertFalse(lint.verify_report(report, self.root)['business_approved'])
        expected_fixture_revenue, deliberately_wrong_value = 100, 999
        self.assertNotEqual(deliberately_wrong_value, expected_fixture_revenue)


if __name__ == '__main__':
    unittest.main()
