"""Safe operator diagnostics without changing retained extraction contracts."""
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'
sys.path.insert(0, str(SCRIPTS))
import run_source_adapter as runner
from source_adapters.base import Report, bounded, validate_files
from source_adapters.errors import SourceAdapterError
from source_adapters.registry import parse


class SourceAdapterDiagnosticTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='PRIVATE-source-diagnostics-')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.root = self.base / 'private-input'
        self.root.mkdir()
        self.output = self.base / 'private-output.json'
        self.marker = 'private-expression-marker'
        self.source = self.root / 'query.sql'
        self.source.write_text("SELECT '" + self.marker + "' AS value")

    def invoke(self, args=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                code = runner.main(args if args is not None else [str(self.root), '--source',
                                                               'snowflake', '--output', str(self.output)])
            except SystemExit as exc:
                code = exc.code
        for private in (str(self.base), self.marker, 'PRIVATE-source-diagnostics-', 'private-input'):
            self.assertNotIn(private, stdout.getvalue() + stderr.getvalue())
        diagnostics = [json.loads(line) for line in stderr.getvalue().splitlines()]
        for row in diagnostics:
            self.assertEqual(row['kind'], 'source_adapter_diagnostic')
            self.assertEqual(row['schema_version'], 1)
            self.assertEqual(row['retry'], 'investigate_before_retry')
            self.assertTrue(row['hint'])
        return code, json.loads(stdout.getvalue()) if stdout.getvalue() else None, diagnostics

    def assert_error(self, expected, args=None):
        code, stdout, errors = self.invoke(args)
        self.assertEqual(code, 1)
        self.assertIsNone(stdout)
        self.assertEqual([row['code'] for row in errors], [expected])
        self.assertEqual(errors[0]['status'], 'error')
        return errors[0]

    def test_invalid_arguments_do_not_echo_untrusted_values(self):
        code, stdout, errors = self.invoke(['--source', self.marker, '--unknown', str(self.root)])
        self.assertEqual(code, 2)  # argparse's prior nonzero exit convention
        self.assertIsNone(stdout)
        self.assertEqual(errors[0]['code'], 'source.invalid_arguments')
        self.assert_error('source.root_and_output_required', ['--source', 'snowflake'])

    def test_input_and_output_preconditions_are_distinct_and_non_destructive(self):
        original = self.source.read_bytes()
        cases = [
            (self.base / 'missing', self.output, 'source.input_missing'),
            (self.source, self.output, 'source.unsafe_root'),
            (self.root, self.root / 'new.json', 'source.output_inside_input'),
            (self.root, self.base / 'missing' / 'new.json', 'source.output_parent_missing'),
            (self.root, self.source / 'new.json', 'source.output_inside_input'),
        ]
        for source, output, expected in cases:
            with self.subTest(expected=expected):
                self.assert_error(expected, [str(source), '--source', 'snowflake', '--output', str(output)])
        self.output.write_text('keep-existing')
        with patch.object(runner, 'parse') as parser:
            error = self.assert_error('source.output_exists')
            parser.assert_not_called()
        self.assertIn('verifying its pinned input and component hashes', error['hint'])
        self.assertEqual(self.output.read_text(), 'keep-existing')
        self.assertEqual(self.source.read_bytes(), original)
        self.assertEqual(list(self.root.iterdir()), [self.source])

    def test_redirected_destinations_and_file_parents_remain_rejected(self):
        target = self.base / 'approved'; target.mkdir()
        link = self.base / 'redirect'; link.symlink_to(target, target_is_directory=True)
        self.assert_error('source.redirected_output', [str(self.root), '--source', 'snowflake',
                                                      '--output', str(link / 'new.json')])
        self.output.write_text('keep-existing')
        self.assert_error('source.output_parent_invalid', [str(self.root), '--source', 'snowflake',
                                                          '--output', str(self.output / 'new.json')])
        self.assertEqual(list(target.iterdir()), [])
        loop = self.base / 'loop'; loop.symlink_to(loop)
        self.assert_error('source.unsafe_root', [str(loop), '--source', 'snowflake',
                                               '--output', str(target / 'new.json')])
        self.assert_error('source.redirected_output', [str(self.root), '--source', 'snowflake',
                                                      '--output', str(loop / 'new.json')])

    def test_scan_limits_and_unsupported_objects_have_typed_diagnostics(self):
        for constant, value, expected in [('MAX_FILE_BYTES', 2, 'source.byte_limit'),
                                          ('MAX_TOTAL_BYTES', 2, 'source.snapshot_limit'),
                                          ('MAX_FILES', 0, 'source.entry_limit'),
                                          ('MAX_DEPTH', 0, 'source.path_depth_limit')]:
            with self.subTest(constant=constant), patch.object(runner, constant, value):
                self.assert_error(expected)
                self.assertFalse(self.output.exists())
        self.source.unlink()
        import os
        os.mkfifo(self.source)
        self.assert_error('source.non_regular_file')

    def test_dependency_errors_use_exception_types_and_names_never_messages(self):
        errors = [
            (ModuleNotFoundError(self.marker, name='yaml'), 'source.dependency_missing'),
            (ImportError(self.marker, name='lkml.parser'), 'source.dependency_unavailable'),
            (ImportError(self.marker), 'source.import_failed'),
            (ModuleNotFoundError(self.marker, name=self.marker), 'source.import_failed'),
            (ValueError('source.output_exists'), 'source.invalid_input'),
            (SourceAdapterError(self.marker), 'source.invalid_input'),
        ]
        for exc, expected in errors:
            with self.subTest(expected=expected), patch.object(runner, 'parse', side_effect=exc):
                self.assert_error(expected)
                self.assertFalse(self.output.exists())

    def test_io_failure_stage_does_not_guess_manifest_or_dependency(self):
        for target, exc, expected in [
            ('collect', PermissionError(self.marker), 'source.input_permission_denied'),
            ('collect', FileNotFoundError(self.marker), 'source.input_unavailable'),
            ('parse', FileNotFoundError(self.marker), 'source.parser_io_error'),
        ]:
            with self.subTest(expected=expected), patch.object(runner, target, side_effect=exc):
                self.assert_error(expected)
        with patch('source_adapters.filesystem.os.open', side_effect=PermissionError(self.marker)):
            self.assert_error('source.output_permission_denied')

    @unittest.skipUnless(importlib.util.find_spec('sqlglot'), 'Optional pinned SQL parser')
    def test_success_stdout_and_full_result_contract_are_unchanged(self):
        text = self.source.read_text()
        expected = parse('snowflake', {'query.sql': text})
        expected['acquisition'] = {'mode': 'supplied_snapshot', 'omissions': [],
                                   'completeness': 'not_established', 'network_calls': 0}
        code, stdout, errors = self.invoke()
        self.assertEqual(code, 0)
        self.assertEqual(errors, [])
        self.assertEqual(stdout, {'status': 'subset_parsed', 'files': 1,
                                 'objects': len(expected['objects']), 'gaps': 0,
                                 'omissions': 0, 'native_validation': 'not_run'})
        self.assertEqual(json.loads(self.output.read_text()), expected)
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.source.read_text(), text)

    def test_real_cli_missing_optional_dependency_preserves_partial_evidence(self):
        # -S selects a clean stdlib-only environment without changing the host.
        completed = subprocess.run([sys.executable, '-S', str(SCRIPTS / 'run_source_adapter.py'),
                                    str(self.root), '--source', 'snowflake', '--output', str(self.output)],
                                   capture_output=True, text=True, timeout=20)
        self.assertEqual(completed.returncode, 2, completed.stderr)
        self.assertNotIn(self.marker, completed.stdout + completed.stderr)
        self.assertNotIn(str(self.base), completed.stdout + completed.stderr)
        errors = [json.loads(row) for row in completed.stderr.splitlines()]
        self.assertIn('source.dependency_unavailable', [row['code'] for row in errors])
        result = json.loads(self.output.read_text())
        self.assertIn(self.marker, result['expressions'][0]['text'])
        self.assertEqual(result['native_validation'], 'not_run')
        self.assertFalse(result['execution_performed'])

    def test_missing_dbt_manifest_and_unsupported_input_are_partial_not_fatal(self):
        args = [str(self.root), '--source', 'dbt', '--output', str(self.output)]
        code, stdout, errors = self.invoke(args)
        self.assertEqual((code, stdout['status']), (2, 'partial'))
        self.assertIn('source.manifest_missing', [row['code'] for row in errors])
        self.assertEqual(json.loads(self.output.read_text())['execution_performed'], False)
        self.output.unlink()
        (self.root / 'manifest.json').write_text(json.dumps({
            'metadata': {'dbt_schema_version': 'https://schemas.getdbt.com/dbt/manifest/v1.json'}}))
        code, _, errors = self.invoke(args)
        self.assertEqual(code, 2)
        self.assertIn('source.manifest_unsupported', [row['code'] for row in errors])
        self.assertNotIn('source.manifest_missing', [row['code'] for row in errors])
        self.output.unlink()
        for file in self.root.iterdir():
            file.unlink()
        (self.root / 'opaque.export').write_bytes(b'\x00\xff')
        code, stdout, errors = self.invoke()
        self.assertEqual((code, stdout['omissions']), (2, 1))
        self.assertIn('source.unsupported_input', [row['code'] for row in errors])
        self.assertIn('source.empty_snapshot', [row['code'] for row in errors])

    def test_partial_gap_messages_and_unknown_codes_are_not_disclosed(self):
        report = Report('snowflake', {'query.sql': self.source.read_text()})
        report.gap('query.sql', self.marker, str(self.root))
        with patch.object(runner, 'parse', return_value=copy.deepcopy(report.finish())):
            code, _, errors = self.invoke()
        self.assertEqual(code, 2)
        self.assertIn('source.partial_evidence', [row['code'] for row in errors])
        self.assertEqual(json.loads(self.output.read_text())['gaps'][0]['message'], str(self.root))

    def test_typed_shared_failures_preserve_valueerror_compatibility(self):
        with self.assertRaisesRegex(SourceAdapterError, 'source.unsafe_path') as raised:
            validate_files({'../query.sql': 'select 1'})
        self.assertIsInstance(raised.exception, ValueError)
        with patch('source_adapters.base.MAX_NODES', 1):
            with self.assertRaisesRegex(ValueError, 'source.structure_limit'):
                bounded({'nested': []})


if __name__ == '__main__':
    unittest.main()
