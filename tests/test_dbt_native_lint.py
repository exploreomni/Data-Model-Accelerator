"""Native lint's zero exit, omitted-file and template safety boundaries."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import dbt_native_lint as native

V2 = {'distribution': 'dbt', 'version': '2.0.8'}


class NativeLintTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.body = b'SELECT 1 AS id\n'
        (self.root / 'orders.sql').write_bytes(self.body)
        self.manifest = {'schema_version': 1, 'kind': 'sql_lint_manifest',
                         'expected_execution_units': ['orders'], 'files': [{
                             'path': 'orders.sql', 'sha256': hashlib.sha256(self.body).hexdigest(),
                             'role': 'model_sql', 'format': 'sql', 'execution_units': ['orders'], 'source_paths': []}]}

    def run_native(self, rows, *, exit_code=0):
        def run(argv, work):
            if argv[-1] == '--version':
                return 0, b'dbt 2.0.8\n', b''
            return exit_code, json.dumps(rows).encode(), b''
        with patch.object(native, 'runtime_identity', return_value={'pin': 'synthetic'}), patch.object(native, '_run', side_effect=run):
            return native.lint_native(self.root, self.manifest, V2, 'snowflake', executable='/synthetic/dbt', execute=True)

    def test_zero_exit_with_violations_fails(self):
        report = self.run_native([{'filepath': 'models/model_0000.sql', 'violations': [{'code': 'CP01', 'description': 'PRIVATE SQL', 'start_line_no': 1}]}])
        self.assertEqual(report['exit_code'], 0)
        self.assertEqual(report['status'], 'failed')
        self.assertNotIn('PRIVATE SQL', json.dumps(report))
        self.assertEqual(report['data_accuracy'], 'not_run')

    def test_missing_or_wrong_file_never_passes(self):
        for rows in ([], [{'filepath': 'wrong.sql', 'violations': []}], [{'filepath': 'models/model_0000.sql'}]):
            with self.subTest(rows=rows):
                self.assertEqual(self.run_native(rows)['status'], 'failed')

    def test_undeclared_sql_and_changed_bytes_fail(self):
        rows = [{'filepath': 'models/model_0000.sql', 'violations': []}]
        self.assertEqual(self.run_native(rows)['status'], 'passed')
        (self.root / 'unreviewed.sql').write_text('SELECT 2')
        self.assertEqual(self.run_native(rows)['status'], 'failed')
        (self.root / 'orders.sql').write_text('SELECT 99')
        with self.assertRaisesRegex(ValueError, 'changed_input'):
            self.run_native(rows)

    def test_source_jinja_and_suppressions_never_enter_native_command(self):
        for body in ("{{ run_query('dangerous') }}", 'SELECT 1 -- noqa: CP01\n'):
            (self.root / 'orders.sql').write_text(body)
            self.manifest['files'][0]['sha256'] = hashlib.sha256(body.encode()).hexdigest()
            with patch.object(native, 'runtime_identity', return_value={}), patch.object(native, '_run', return_value=(0, b'dbt 2.0.8', b'')) as run:
                result = native.lint_native(self.root, self.manifest, V2, 'snowflake', executable='/synthetic/dbt', execute=True)
            self.assertEqual(run.call_count, 1)  # version only
            self.assertEqual(result['status'], 'partial')
            self.assertFalse(result['execution_performed'])

    def test_plan_and_oss_do_not_probe_or_execute(self):
        with patch.object(native, 'runtime_identity', side_effect=AssertionError('probe')), patch.object(native, '_run', side_effect=AssertionError('execute')):
            plan = native.lint_native(self.root, self.manifest, V2, 'snowflake', executable='/absent')
            oss = native.lint_native(self.root, self.manifest, {'distribution': 'dbt_oss', 'version': '2.0.8'}, 'snowflake', executable='/absent', execute=True)
        self.assertEqual(plan['status'], 'not_run')
        self.assertEqual(oss['status'], 'unsupported')

    def test_file_added_during_execution_invalidates_coverage(self):
        def run(argv, work):
            if argv[-1] == '--version':
                return 0, b'dbt 2.0.8', b''
            (self.root / 'late.sql').write_text('SELECT 9')
            return 0, b'[{"filepath":"models/model_0000.sql","violations":[]}]', b''
        with patch.object(native, 'runtime_identity', return_value={}), patch.object(native, '_run', side_effect=run):
            with self.assertRaisesRegex(ValueError, 'inventory_changed'):
                native.lint_native(self.root, self.manifest, V2, 'snowflake', executable='/synthetic/dbt', execute=True)


if __name__ == '__main__':
    unittest.main()
