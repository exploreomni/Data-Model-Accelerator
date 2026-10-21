"""Synthetic offline workflow coverage; no customer exports or native execution."""
import json
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'
sys.path.insert(0, str(SCRIPTS))
from periscope_workflow import run_periscope_workflow

VIEW = 'Database Name: warehouse\nSettings:\n  Materialize View: true\n  Metadata:\n    Owner: synthetic\n'
SNIPPET = 'Parameters: [Amount]\nSettings:\n  Metadata:\n    Owner: synthetic\n'
DASH = 'display_name: Revenue\ndashboard_preferences:\n  settings:\n    owner: synthetic\n'


@unittest.skipUnless(importlib.util.find_spec('yaml'), 'Optional PyYAML source parser dependency required')
class PeriscopeWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.source = self.base / 'source'
        self.source.mkdir()

    def write(self, path, content):
        target = self.source / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content if isinstance(content, bytes) else content.encode())
        return target

    def run_flow(self, output='result', **kwargs):
        return run_periscope_workflow(self.source, self.base / output, inspect_git=False, **kwargs)

    def contract(self, report, index=0, output='result'):
        return json.loads((self.base / output / report['extraction'][index]['contract_path']).read_text())

    def test_views_only_discovers_and_extracts_without_generic_sql_false_positive(self):
        self.write('nested/cdt/views/orders/orders.yaml', VIEW)
        self.write('nested/cdt/views/orders/orders.sql', 'select amount from raw.orders')
        self.write('unrelated.sql', 'select amount from periscope.orders')
        report = self.run_flow()
        self.assertEqual([x['project_root'] for x in report['extraction']], ['nested/cdt'])
        contract = self.contract(report)
        self.assertEqual(contract['source'], 'periscope')
        self.assertTrue(any(o['kind'] == 'view' for o in contract['objects']))
        rows = {r['path']: r for r in report['coverage']['files']}
        self.assertEqual(rows['unrelated.sql']['status'], 'excluded')
        self.assertEqual(rows['unrelated.sql']['source_types'], ['generic_sql'])
        self.assertEqual(report['coverage']['known_file_denominator'], 3)
        self.assertEqual(sum(report['coverage']['counts'].values()), 3)
        self.assertFalse(report['execution_performed'])
        self.assertEqual(report['native_validation'], 'not_run')

    def test_snippets_only_mixed_monorepo_and_missing_sidecar(self):
        self.write('apps/cdt/snippets/ratio/ratio.yaml', SNIPPET)
        self.write('apps/cdt/snippets/ratio/ratio.js', 'do_not_execute()')
        self.write('analytics/dbt_project.yml', 'name: fixture\nconfig-version: 2\n')
        self.write('analytics/models/model.sql', 'select 1')
        report = self.run_flow()
        contract = self.contract(report)
        self.assertTrue(any(o['kind'] == 'snippet' for o in contract['objects']))
        self.assertIn('periscope.sql_missing', {g['code'] for g in contract['gaps']})
        rows = {r['path']: r for r in report['coverage']['files']}
        self.assertEqual(rows['apps/cdt/snippets/ratio/ratio.js']['status'], 'unsupported')
        self.assertEqual(rows['analytics/models/model.sql']['source_types'], ['dbt'])
        self.assertEqual(rows['analytics/models/model.sql']['status'], 'excluded')

    def test_old_dashboard_marker_still_extracts_and_does_not_execute(self):
        self.write('dashboards/revenue.' + 'a' * 32 + '/revenue.yaml', DASH)
        sentinel = self.base / 'not-executed'
        self.write('custom_modules/danger.py', 'from pathlib import Path\nPath(%r).touch()' % str(sentinel))
        self.write('custom_modules/danger.r', 'system("do_not_execute")')
        with patch('subprocess.run', side_effect=AssertionError('source execution forbidden')):
            report = self.run_flow()
        self.assertFalse(sentinel.exists())
        self.assertEqual(len(report['extraction']), 1)
        self.assertTrue(any(o['native_id'] == 'a' * 32 for o in self.contract(report)['objects']))

    def test_false_markers_and_explicit_fallback_keep_format_gaps(self):
        self.write('views/orders/orders.yaml', 'Database Name: warehouse\nSettings: {}')
        self.write('snippets/ratio/ratio.yaml', 'Settings:\n  Owner: wrong nesting')
        self.write('queries.sql', 'SELECT [ratio(x)]')
        report = self.run_flow()
        self.assertEqual(report['status'], 'no_periscope_detected')
        self.assertEqual(report['extraction'], [])
        explicit = self.run_flow('explicit', source_profiles=['periscope:.'])
        self.assertEqual(explicit['profiles'][0]['evidence']['kind'], 'explicit_user_source_profile')
        contract = self.contract(explicit, output='explicit')
        self.assertIn('periscope.unsupported_format', {g['code'] for g in contract['gaps']})
        self.assertEqual(explicit['status'], 'partial')

    def test_ambiguous_binding_and_dialect_records_never_expand_sql(self):
        self.write('snippets/orders/orders.yaml', SNIPPET)
        self.write('snippets/orders/orders.sql', '[Amount]')
        self.write('views/orders/orders.yaml', VIEW)
        self.write('views/orders/orders.sql', 'select [orders]')
        mappings = [{'project_root': '.', 'connection_name': 'warehouse', 'dialect': 'bigquery',
                     'evidence': 'operator-reviewed connection metadata receipt abc'}]
        report = self.run_flow(verified_connection_dialects=mappings)
        self.assertTrue(all(r['status'] == 'unresolved' for r in report['binding_review']))
        contract = self.contract(report)
        edge = next(d for d in contract['dependencies'] if d['details'].get('native_reference') == '[orders]')
        self.assertEqual(edge['details']['resolution'], 'unresolved')
        self.assertIn('sql.dialect_unknown', {g['code'] for g in contract['gaps']})
        self.assertEqual(report['connection_dialects'][0]['status'], 'verification_evidence_recorded')
        self.assertFalse(report['connection_dialects'][0]['applied_to_canonical_parser'])
        self.assertTrue(any(e['text'] == 'select [orders]' for e in contract['expressions']))
        self.assertFalse(any(d['details'].get('kind') == 'reads_from' for d in contract['dependencies']))

    def test_namespace_stable_across_checkout_and_identity_conflicts_visible(self):
        for prefix in ('one', 'two'):
            self.write(prefix + '/dashboards/revenue.' + 'a' * 32 + '/revenue.yaml', DASH)
        identity = {'repository_id': 'repo-123', 'space_ids': {'one': 'space-1', 'two': 'space-2'}}
        first = self.run_flow(source_identity=identity)
        self.assertNotEqual(first['extraction'][0]['qualified_objects'][0]['qualified_id'],
                            first['extraction'][1]['qualified_objects'][0]['qualified_id'])
        other = self.base / 'other-checkout'
        import shutil
        shutil.copytree(self.source, other)
        second = run_periscope_workflow(other, self.base / 'second', source_identity=identity, inspect_git=False)
        self.assertEqual([p['namespace'] for p in first['source_identity']['projects']],
                         [p['namespace'] for p in second['source_identity']['projects']])
        conflict = self.run_flow('conflict', source_identity={'repository_id': 'repo-123', 'space_ids': {'one': 'same', 'two': 'same'}})
        self.assertIn('periscope.source_identity_conflict', {g['code'] for g in conflict['gaps']})

    def test_duplicate_native_tokens_and_dialect_conflicts_remain_reviewable(self):
        for name in ('first', 'second'):
            self.write('dashboards/' + name + '.' + 'a' * 32 + '/' + name + '.yaml', DASH)
        mapping = {'project_root': '.', 'connection_name': 'warehouse', 'dialect': 'bigquery', 'evidence': 'review receipt'}
        report = self.run_flow(verified_connection_dialects=[mapping, dict(mapping, dialect='snowflake')])
        codes = {g['code'] for g in report['gaps']}
        self.assertTrue({'periscope.native_identity_conflict', 'periscope.connection_dialect_conflict'} <= codes)
        self.assertEqual(len(report['extraction'][0]['qualified_objects']), 2)
        self.assertTrue(all(m['status'] == 'conflict' for m in report['connection_dialects']))

    def test_complete_known_denominator_and_unknown_excluded_subtrees(self):
        self.write('views/orders/orders.yaml', VIEW)
        self.write('views/orders/orders.sql', 'select 1')
        self.write('views/orders/big.sql', 'X' * 400)
        self.write('views/orders/output.bin', b'\0bad')
        self.write('.env', 'DO_NOT_READ=secret')
        self.write('node_modules/hidden.js', 'not read')
        report = self.run_flow(max_file_bytes=200)
        coverage = report['coverage']
        self.assertEqual(coverage['known_file_denominator'], 5)
        self.assertEqual(sum(coverage['counts'].values()), 5)
        self.assertEqual(coverage['counts']['unreadable'], 1)
        self.assertEqual(coverage['counts']['unsupported'], 1)
        self.assertEqual(coverage['counts']['excluded'], 1)
        self.assertIsNone(coverage['repository_file_denominator'])
        self.assertEqual(coverage['excluded_subtrees'][0]['file_count'], None)
        self.assertNotIn('DO_NOT_READ', json.dumps(report))

    def test_scan_limit_and_reread_failure_are_not_clean_coverage(self):
        self.write('views/orders/orders.yaml', VIEW)
        self.write('views/orders/orders.sql', 'select 1')
        limited = self.run_flow(max_files=1, source_profiles=['periscope:.'])
        self.assertFalse(limited['coverage']['enumeration_complete'])
        self.assertIsNone(limited['coverage']['repository_file_denominator'])
        with patch('periscope_workflow.read_assigned', side_effect=OSError('synthetic failure')):
            failed = self.run_flow('failure')
        self.assertEqual(failed['coverage']['counts']['unreadable'], 2)
        self.assertEqual(failed['extraction'][0]['status'], 'no_readable_evidence')

    def test_output_overlap_and_unverified_mapping_rejected(self):
        self.write('views/orders/orders.yaml', VIEW)
        with self.assertRaises(ValueError):
            run_periscope_workflow(self.source, self.source / 'output', inspect_git=False)
        with self.assertRaises(ValueError):
            self.run_flow(verified_connection_dialects=[{'project_root': '.', 'connection_name': 'warehouse',
                                                        'dialect': 'bigquery', 'evidence': ''}])


if __name__ == '__main__':
    unittest.main()
