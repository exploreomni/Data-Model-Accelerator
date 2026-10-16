"""Synthetic versioned receipt adversaries, not claims of native qualification.

Real positive/negative native execution is required separately by the explicit
run_dbt_runtime_qualification.py CI lanes for both installed distributions.
"""
import copy
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'
sys.path.insert(0, str(SCRIPTS))
from ae_common import snapshot
from dbt_runtime import driver_contract, runtime_argv, validate_selection
import run_dbt_project as runner
import verify_dbt_evidence as checker
from test_dbt_evidence import make_fixture


def versioned_fixture(root, distribution='dbt'):
    receipt_path = make_fixture(root)
    receipt = json.loads(receipt_path.read_text())
    selected = validate_selection({'distribution': distribution, 'version': '2.0.8'})
    start = checker.instant(receipt['execution']['started_at'], 'fixture')
    timestamp = lambda offset: (start + timedelta(seconds=offset)).isoformat()
    receipt.update(schema_version=2, expected_dbt_version='2.0.8')
    receipt['project_snapshot']['captured_at'] = timestamp(-1)
    receipt['expected_node_ids'].remove('snapshot.billing.history')
    for name in ('preflight_manifest', 'manifest', 'run_results'):
        path = root / receipt[name]['path']
        document = json.loads(path.read_text())
        document['metadata']['dbt_version'] = '2.0.8'
        if name == 'run_results':
            document['metadata'].pop('invocation_started_at')
            document['results'] = [r for r in document['results'] if not r['unique_id'].startswith('snapshot.')]
            for record in document['results']:
                record.pop('compiled')
            document['args'] = {'command': 'build', 'which': 'build', 'full_refresh': False,
                                'static_analysis': 'Baseline' if distribution == 'dbt' else 'Off'}
        else:
            document['nodes'].pop('snapshot.billing.history')
            for node in document['nodes'].values():
                node['config']['static_analysis'] = 'off' if distribution == 'dbt_oss' and name == 'manifest' else 'baseline'
                if distribution == 'dbt_oss' and name == 'manifest':
                    node['static_analysis_off_reason'] = 'configuredoff'
        path.write_text(json.dumps(document))
        receipt[name]['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    identity = {'distribution': distribution, 'version': '2.0.8', 'package': 'dbt' if distribution == 'dbt' else 'dbt-oss',
                'files': [{'path': str(root / 'synthetic-runtime' / name), 'sha256': 'a' * 64}
                          for name in ('bin/dbt', 'bin/python', 'pyvenv.cfg', 'METADATA', '_core.abi3.so')]}
    driver = dict(path=str(root / 'preinstalled-driver'), sha256=driver_contract('Linux', 'x86_64')['sha256'], version='1.5.4')
    request = {'schema_version': 2, 'project_sha256': snapshot(root / 'project')['sha256'], 'adapter_type': 'duckdb',
               'profile': 'qualification', 'target': 'qualification', 'profiles_dir': str(root / 'profiles'),
               'allowed_destinations': [{'database': 'qualification', 'schema': 'main'}],
               'expected_profile': {'path': str(root / 'warehouse.duckdb')}, 'timeout_seconds': 30,
               'dbt_runtime': selected, 'runtime_identity': identity, 'driver': driver}
    request_path = root / 'request.json'
    request_path.write_text(json.dumps(request))
    receipt['request'] = {'path': 'request.json', 'sha256': hashlib.sha256(request_path.read_bytes()).hexdigest()}
    receipt['runtime'] = {'selection': selected, 'identity': identity,
                          'observed': {'distribution': distribution, 'version': '2.0.8',
                                       'version_output': ('dbt' if distribution == 'dbt' else 'dbt-oss') + ' 2.0.8'},
                          'driver': dict(driver, platform='Linux/x86_64'), 'effective_analysis_mode': selected['analysis_mode']}
    receipt['profile_sha256'] = 'b' * 64
    version_path = root / 'version.txt'
    version_path.write_text(receipt['runtime']['observed']['version_output'] + '\n')
    receipt['version_output'] = {'path': 'version.txt', 'sha256': hashlib.sha256(version_path.read_bytes()).hexdigest()}
    executable = identity['files'][0]['path']
    commands = {'version': {'args': [executable, '--version'], 'exit_code': 0,
                            'started_at': timestamp(-8), 'finished_at': timestamp(-6)}}
    for verb, folder, offsets in [('parse', 'preflight', (-4, -2)), ('build', 'build', (0, 12))]:
        commands[verb] = {'args': runtime_argv(executable, verb, root / 'project', request['profiles_dir'], request['profile'],
                                               request['target'], root / folder, selected),
                          'exit_code': 0, 'started_at': timestamp(offsets[0]), 'finished_at': timestamp(offsets[1])}
    receipt['commands'] = commands
    receipt_path.write_text(json.dumps(receipt))
    return receipt_path, receipt


class VersionedReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.path, self.receipt = versioned_fixture(self.root)

    def check(self):
        self.path.write_text(json.dumps(self.receipt))
        return checker.verify(self.path)

    def mutate(self, name, change):
        path = self.root / self.receipt[name]['path']
        value = json.loads(path.read_text())
        change(value)
        path.write_text(json.dumps(value))
        self.receipt[name]['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()

    def test_versioned_artifact_omissions_have_independent_bindings(self):
        report = self.check()
        self.assertTrue(report['evidence_complete'], report)
        self.assertEqual(report['runtime_distribution'], 'dbt')
        self.assertEqual(report['counts']['runnable_nodes'], 4)
        self.assertEqual(report['effective_analysis_mode'], 'baseline')

    def test_original_request_can_omit_default_mode_features_without_rebinding(self):
        self.mutate('request', lambda data: data.update(dbt_runtime={'distribution': 'dbt', 'version': '2.0.8'}))
        original = (self.root / 'request.json').read_bytes()
        report = self.check()
        self.assertTrue(report['evidence_complete'], report)
        self.assertEqual((self.root / 'request.json').read_bytes(), original)

    def test_oss_analysis_off_is_explicit_not_sql_analysis_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            path, receipt = versioned_fixture(Path(temp).resolve(), 'dbt_oss')
            report = checker.verify(path)
            self.assertTrue(report['evidence_complete'], report)
            self.assertEqual(report['effective_analysis_mode'], 'none')
            receipt['runtime']['effective_analysis_mode'] = 'strict'
            path.write_text(json.dumps(receipt))
            self.assertFalse(checker.verify(path)['evidence_complete'])

    def test_distribution_cannot_be_inferred_or_rebound_from_manifest_schema(self):
        self.receipt['runtime']['observed']['distribution'] = 'dbt_oss'
        self.assertFalse(self.check()['evidence_complete'])
        self.receipt.pop('runtime')
        self.assertFalse(self.check()['evidence_complete'])

    def test_request_and_runtime_pins_cannot_drift(self):
        for mutate in (lambda r: r['runtime']['identity']['files'][0].update(sha256='c' * 64),
                       lambda r: r['runtime']['driver'].update(sha256='d' * 64),
                       lambda r: r['runtime']['selection'].update(version='2.0.9')):
            before = copy.deepcopy(self.receipt)
            mutate(self.receipt)
            self.assertFalse(self.check()['evidence_complete'])
            self.receipt = before

    def test_command_scope_target_and_legacy_flags_cannot_be_rebound(self):
        for extra in (['--select', 'fact'], ['--empty'], ['--defer'], ['--no-partial-parse'], ['--vars', '{"x":1}']):
            before = copy.deepcopy(self.receipt)
            self.receipt['commands']['build']['args'].extend(extra)
            self.assertFalse(self.check()['evidence_complete'])
            self.receipt = before
        args = self.receipt['commands']['build']['args']
        args[args.index('--target') + 1] = 'prod'
        self.assertFalse(self.check()['evidence_complete'])

    def test_success_process_cannot_hide_missing_or_stale_results(self):
        self.mutate('run_results', lambda data: data['results'].pop())
        self.assertFalse(self.check()['evidence_complete'])

    def test_stale_result_even_with_current_hash_is_not_complete(self):
        self.mutate('run_results', lambda data: data['metadata'].update(generated_at='2020-01-01T00:00:00+00:00'))
        self.assertFalse(self.check()['evidence_complete'])

    def test_observed_version_output_is_byte_bound(self):
        (self.root / 'version.txt').write_text('dbt-oss 2.0.8\n')
        self.assertFalse(self.check()['evidence_complete'])

    def test_compiled_sql_and_mode_must_match_manifest_and_request(self):
        self.mutate('run_results', lambda data: data['results'][0].update(compiled_code='select 999'))
        self.assertFalse(self.check()['evidence_complete'])

    def test_fallback_does_not_satisfy_strict_or_baseline_request(self):
        self.mutate('run_results', lambda data: data['args'].update(static_analysis='Off'))
        self.assertFalse(self.check()['evidence_complete'])

    def test_schema_one_stays_strict_for_v2_artifact_omissions(self):
        self.receipt['schema_version'] = 1
        self.receipt['expected_dbt_version'] = '1.12.4'
        self.assertFalse(self.check()['evidence_complete'])

    def test_preflight_chronology_source_hash_and_invocation_are_bound(self):
        self.mutate('manifest', lambda data: data['metadata'].update(invocation_id='unrelated'))
        self.assertFalse(self.check()['evidence_complete'])

    def test_version_probe_and_every_command_must_succeed(self):
        for command in ('version', 'parse', 'build'):
            self.receipt['commands'][command]['exit_code'] = 1
            self.assertFalse(self.check()['evidence_complete'])
            self.receipt['commands'][command]['exit_code'] = 0


class NativeExecutionBoundaryTests(unittest.TestCase):
    def test_execute_is_required_before_file_read_or_version_probe(self):
        process = unittest.mock.Mock(side_effect=AssertionError('unexpected execution'))
        with self.assertRaises(ValueError):
            runner.run_project('/missing', '/missing', '/missing', '/missing', execute=False, process=process)
        process.assert_not_called()

    def test_native_step_does_not_capture_unbounded_memory_or_inherit_environment(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            env = {'HOME': str(root / 'isolated'), 'PATH': '/usr/bin:/bin'}
            def fake(args, **kwargs):
                self.assertEqual(kwargs['env'], env)
                self.assertNotIn('capture_output', kwargs)
                self.assertTrue(callable(kwargs['preexec_fn']))
                kwargs['stdout'].write(b'private diagnostics')
                return subprocess.CompletedProcess(args, 1)
            result = runner._native_step(['/synthetic/dbt', 'build'], root / 'step', 1, env, fake, root)
            self.assertEqual(result['exit_code'], 1)
            self.assertEqual((root / 'step/stdout.txt').stat().st_mode & 0o777, 0o600)

    def test_timeout_is_never_success(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            def timeout(*args, **kwargs):
                raise subprocess.TimeoutExpired(args[0], kwargs['timeout'])
            self.assertEqual(runner._native_step(['/synthetic/dbt'], root / 'step', 1, {}, timeout, root)['exit_code'], 124)

    def test_unqualified_selection_profile_or_pin_never_reaches_version_probe(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            path, receipt = versioned_fixture(root)
            request_path = root / 'request.json'
            original = json.loads(request_path.read_text())
            profiles = root / 'profiles'
            profiles.mkdir()
            (profiles / 'profiles.yml').write_text('profile values supplied by reader double')
            executable = root / 'synthetic-dbt'
            executable.write_text('non-executable identity double')
            process = unittest.mock.Mock(side_effect=AssertionError('unexpected native invocation'))
            profile = {'qualification': {'outputs': {'qualification': {
                'type': 'duckdb', 'path': str(root / 'warehouse.duckdb'), 'schema': 'main', 'threads': 1}}}}
            mutations = [lambda r: r['dbt_runtime'].update(version='2.0.9'),
                         lambda r: r['dbt_runtime'].update(analysis_mode='strict'),
                         lambda r: r['dbt_runtime'].update(features=['checks']),
                         lambda r: r['runtime_identity']['files'][0].update(sha256='c' * 64),
                         lambda r: r['driver'].update(sha256='d' * 64)]
            for mutate in mutations:
                request = copy.deepcopy(original)
                mutate(request)
                request_path.write_text(json.dumps(request))
                with patch.object(runner, '_yaml', return_value=profile), patch('dbt_runtime.runtime_identity', return_value=original['runtime_identity']):
                    with self.assertRaises((OSError, ValueError)):
                        runner.run_project(root / 'project', request_path, root / 'run', executable, execute=True, process=process)
            request_path.write_text(json.dumps(original))
            profile['qualification']['outputs']['qualification']['extensions'] = ['httpfs']
            with patch.object(runner, '_yaml', return_value=profile), self.assertRaises(ValueError):
                runner.run_project(root / 'project', request_path, root / 'run', executable, execute=True, process=process)
            process.assert_not_called()

    def test_output_symlink_cannot_redirect_native_work_into_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            _, receipt = versioned_fixture(root)
            output = root / 'redirected'
            output.symlink_to(root / 'project', target_is_directory=True)
            executable = root / 'synthetic-dbt'
            executable.write_text('not executed')
            process = unittest.mock.Mock(side_effect=AssertionError('unexpected native invocation'))
            with self.assertRaises(ValueError):
                runner.run_project(root / 'project', root / 'request.json', output, executable, execute=True, process=process)
            process.assert_not_called()


if __name__ == '__main__':
    unittest.main()
