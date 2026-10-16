"""Fail-closed expectations for the opt-in synthetic native feature lane."""
import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import run_dbt_feature_qualification as qualification


def manifest():
    nodes = {uid: {'unique_id': uid, 'resource_type': 'check', 'config': {'enabled': True, 'severity': 'ERROR'}}
             for uid in qualification.CHECK_IDS}
    nodes.update({uid: {'unique_id': uid, 'resource_type': 'model'} for uid in qualification.MODEL_IDS})
    return {'nodes': nodes, 'disabled': {}}


def results(failure=None):
    return [{'unique_id': uid, 'status': 'fail' if uid.endswith('.' + str(failure)) else 'pass',
             'failures': 1 if uid.endswith('.' + str(failure)) else 0} for uid in sorted(qualification.CHECK_IDS)]


def console(failure=None):
    stdout = '\n'.join(('Failed' if name == failure else 'Passed') + ' [ 0.01s] check ' + name
                       for name in qualification.CHECKS) + '\n'
    stderr = '' if failure is None else (
        "[error] [CheckFailed (dbt1650)]: check '" + failure + "' failed with 1 violation(s)\n"
        '│ unique_id │\n│ ' + qualification.OFFENDER + ' │\n')
    return (0 if failure is None else 1), stdout.encode(), stderr.encode()


class FeatureQualificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='dma-feature-qualification-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def test_plan_never_probes_executes_installs_or_writes(self):
        output = self.root / 'not-created'
        with (patch.object(qualification, '_load_duckdb', side_effect=AssertionError('dependency')),
                patch.object(qualification, 'runtime_identity', side_effect=AssertionError('probe')),
                patch.object(qualification, '_run', side_effect=AssertionError('execute'))):
            report = qualification.qualify('dbt', '/absent/dbt', '/absent/driver', output)
        self.assertEqual(report['status'], 'not_run')
        self.assertFalse(report['execution_performed'])
        self.assertFalse(output.exists())

    def test_only_new_private_external_output_is_allowed(self):
        output = qualification._new_output(self.root / 'evidence')
        self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o700)
        with self.assertRaises(FileExistsError):
            qualification._new_output(output)
        with self.assertRaisesRegex(ValueError, 'external_output_required'):
            qualification._new_output(qualification.REPOSITORY / 'must-not-create-feature-evidence')
        alias = self.root / 'redirect'; alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'canonical_output_required'):
            qualification._new_output(alias / 'evidence2')

    def test_driver_bytes_must_match_pin_and_be_preserved(self):
        path = self.root / 'driver'; raw = b'synthetic-local-driver'; path.write_bytes(raw)
        expected = {'sha256': hashlib.sha256(raw).hexdigest()}
        self.assertEqual(qualification._driver_bytes(path, expected), raw)
        self.assertEqual(path.read_bytes(), raw)
        with self.assertRaisesRegex(ValueError, 'driver_pin_mismatch'):
            qualification._driver_bytes(path, {'sha256': '0' * 64})
        alias = self.root / 'driver-link'; alias.symlink_to(path)
        with self.assertRaisesRegex(ValueError, 'canonical_driver_required'):
            qualification._driver_bytes(alias, expected)

    def test_exact_manifest_denominator_and_enabled_error_configuration(self):
        source = manifest()
        self.assertEqual(set(qualification._verify_manifest(source)), qualification.CHECK_IDS)
        check = next(iter(qualification.CHECK_IDS))
        for change in ({'enabled': False}, {'severity': 'WARN'}, {'severity': 'ERROR', 'enabled': 1}):
            broken = copy.deepcopy(source); broken['nodes'][check]['config'].update(change)
            with self.assertRaisesRegex(ValueError, 'disabled_or_nonerror_check'):
                qualification._verify_manifest(broken)
        broken = copy.deepcopy(source); broken['nodes'].pop(check)
        with self.assertRaisesRegex(ValueError, 'check_manifest_denominator'):
            qualification._verify_manifest(broken)

    def test_native_result_denominator_duplicate_status_and_boolean_count(self):
        qualification._verify_results(results(), None)
        qualification._verify_results(results(qualification.CHECKS[0]), qualification.CHECKS[0])
        bad = [results()[:1], [results()[0], results()[0]],
               [dict(results()[0], status='skipped'), results()[1]],
               [dict(results()[0], failures=False), results()[1]]]
        for rows in bad:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                qualification._verify_results(rows, None)

    def test_console_success_requires_both_actual_check_outcomes(self):
        self.assertEqual(qualification._verify_check_output(*console(), None)['source'], 'run_results_and_console')
        for output in (b'', b'Finished successfully\n', b'Passed [0.01s] check dma_model_descriptions\n'):
            with self.assertRaisesRegex(ValueError, 'check_output_denominator'):
                qualification._verify_check_output(0, output, b'', None)
        with self.assertRaisesRegex(ValueError, 'passing_check_failed'):
            qualification._verify_check_output(1, console()[1], b'', None)

    def test_negative_fixture_requires_expected_count_resource_and_other_pass(self):
        failure = qualification.CHECKS[0]
        code, stdout, stderr = console(failure)
        outcome = qualification._verify_check_output(code, stdout, stderr, failure)
        self.assertEqual(outcome['violating_resource_ids'], [qualification.OFFENDER])
        for changed in (stderr.replace(b'1 violation', b'2 violation'),
                        stderr.replace(qualification.OFFENDER.encode(), b'model.other.unexpected'),
                        stderr + b'[error] unexpected failure\n'):
            with self.assertRaises(ValueError):
                qualification._verify_check_output(code, stdout, changed, failure)
        with self.assertRaisesRegex(ValueError, 'unexpected_check_outcome'):
            qualification._verify_check_output(code, stdout.replace(b'Passed', b'Failed'), stderr, failure)
        with self.assertRaisesRegex(ValueError, 'negative_fixture_exit'):
            qualification._verify_check_output(0, stdout, stderr, failure)

    def test_oss_lint_is_explicitly_unsupported_without_calling_lint(self):
        with patch.object(qualification, 'lint_native', side_effect=AssertionError('must not run')):
            report = qualification._lint_cases(self.root, '/absent/dbt', {'distribution': 'dbt_oss', 'version': '2.0.8'})
        self.assertEqual(report['status'], 'unsupported')
        self.assertFalse(report['execution_performed'])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_source_snapshot_detects_additions_mutations_and_rejects_links(self):
        (self.root / 'model.sql').write_text('SELECT 1')
        initial = qualification._snapshot(self.root)
        (self.root / 'later.sql').write_text('SELECT 2')
        self.assertNotEqual(initial, qualification._snapshot(self.root))
        (self.root / 'model.sql').write_text('SELECT 3')
        self.assertNotEqual(initial['model.sql'], qualification._snapshot(self.root)['model.sql'])
        (self.root / 'redirect.sql').symlink_to(self.root / 'model.sql')
        with self.assertRaises((ValueError, OSError)):
            qualification._snapshot(self.root)

    def test_cli_reports_preflight_failure_without_overwriting_output(self):
        existing = self.root / 'existing'; existing.mkdir()
        marker = existing / 'marker'; marker.write_text('unchanged')
        with (patch.object(qualification, '_load_duckdb'), patch.object(qualification, 'runtime_identity', return_value={}),
                patch.object(qualification, 'driver_contract', return_value={'sha256': 'fake'}),
                patch.object(qualification, '_driver_bytes', return_value=b''), contextlib.redirect_stderr(io.StringIO())):
            code = qualification.main(['--distribution', 'dbt', '--dbt', '/absent/dbt', '--driver', '/absent/driver',
                                       '--output', str(existing), '--execute'])
        self.assertEqual(code, 1)
        self.assertEqual(marker.read_text(), 'unchanged')

    def test_report_preserves_only_allowlisted_information_schema_codes(self):
        errors = [
            (qualification.InformationSchemaError('dbt_info_schema.parquet_decode_failed'),
             'dbt_info_schema.parquet_decode_failed'),
            (qualification.InformationSchemaError('dbt_info_schema.unsafe_directory'),
             'dbt_info_schema.unsafe_directory'),
            (qualification.InformationSchemaError('dbt_info_schema.parquet_decode_failed\nsecret-value'),
             'qualification_step_failed:InformationSchemaError'),
            (qualification.InformationSchemaError('dbt_info_schema.secret_value'),
             'qualification_step_failed:InformationSchemaError'),
            (ValueError('dbt_info_schema.parquet_decode_failed'), 'qualification_step_failed:ValueError'),
            (ValueError('dbt.feature_qualification.secret_value'), 'qualification_step_failed:ValueError'),
            (RuntimeError('native /private/source contains secret-value'), 'qualification_step_failed:RuntimeError'),
        ]
        contract = {'adapter': 'duckdb', 'version': 'synthetic', 'platform': 'synthetic', 'sha256': '0' * 64}
        for index, (error, expected) in enumerate(errors):
            output = self.root / str(index)
            with (self.subTest(error=error), patch.object(qualification, '_load_duckdb'),
                  patch.object(qualification, 'runtime_identity', return_value={}),
                  patch.object(qualification, 'driver_contract', return_value=contract),
                  patch.object(qualification, '_driver_bytes', return_value=b''),
                  patch.object(qualification, '_execute', return_value=(0, b'synthetic', b'')),
                  patch.object(qualification, 'observed_version', return_value={}),
                  patch.object(qualification, '_scenario', side_effect=error)):
                report = qualification.qualify('dbt', '/absent/dbt', '/absent/driver', output, execute=True)
                self.assertEqual(report['status'], 'failed')
                self.assertEqual(report['error'], expected)
                saved = json.loads((output / 'report.json').read_text())
                self.assertEqual(saved['error'], expected)
                self.assertNotIn('secret', json.dumps(saved))

    def test_own_fixed_assertion_code_is_preserved(self):
        with self.assertRaises(ValueError) as caught:
            qualification._require(False, 'parse_failed')
        self.assertEqual(qualification._reported_error(caught.exception), 'dbt.feature_qualification.parse_failed')


if __name__ == '__main__':
    unittest.main()
