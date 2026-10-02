"""Execution boundaries use process doubles; native success is covered by replay."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'
sys.path.insert(0, str(SCRIPTS))
from ae_common import snapshot, write_json
from test_dbt_evidence import make_fixture
try:
    import yaml
except ImportError:
    yaml = None


@unittest.skipUnless(yaml, 'optional execution profile reader requires PyYAML')
class DbtProjectRunnerTests(unittest.TestCase):
    def setUp(self):
        import run_dbt_project
        self.runner = run_dbt_project
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        receipt = make_fixture(self.root / 'fixture')
        self.project = receipt.parent / 'project'
        self.manifest = json.loads((receipt.parent / 'preflight_manifest.json').read_text())
        self.profiles = self.root / 'profiles'
        self.profiles.mkdir()
        self.profile_file = self.profiles / 'profiles.yml'
        self.profile_file.write_text(yaml.safe_dump({'qualification': {'target': 'dev', 'outputs': {
            'dev': {'type': 'duckdb', 'path': str(self.root / 'dev.duckdb'), 'schema': 'main', 'threads': 1}}}}))
        self.request = {'schema_version': 1, 'project_sha256': snapshot(self.project)['sha256'],
                        'adapter_type': 'duckdb', 'profile': 'qualification', 'target': 'dev',
                        'profiles_dir': str(self.profiles), 'allowed_destinations': [{'database': 'qualification', 'schema': 'main'}],
                        'expected_profile': {'path': str(self.root / 'dev.duckdb')}, 'timeout_seconds': 10}
        self.request_path = self.root / 'request.json'
        self.output = self.root / 'run'
        # Process doubles need a regular file, independent of system binary symlinks.
        self.executable = self.root / 'fake-dbt'
        self.executable.write_text('# process double only\n')
        self.calls = []

    def run_project(self, process=None, execute=True):
        self.request_path.write_text(json.dumps(self.request))
        return self.runner.run_project(self.project, self.request_path, self.output,
                                       self.executable, execute=execute, process=process or self.fake)

    def fake(self, args, **kwargs):
        self.calls.append(args)
        target = Path(args[args.index('--target-path') + 1])
        target.mkdir(parents=True, exist_ok=True)
        (target / 'manifest.json').write_text(json.dumps(self.manifest))
        # Synthetic processes deliberately do not claim a successful native build.
        return subprocess.CompletedProcess(args, 0 if 'parse' in args else 1, 'captured output', 'captured error')

    def test_preflight_accepts_complete_root_project(self):
        ids = self.runner.validate_preflight(self.manifest, self.request)
        self.assertIn('model.billing.fact', ids)
        self.assertNotIn('model.billing.stg_invoice', ids)

    def test_preflight_rejects_destination_and_incompatible_contracts(self):
        changes = [lambda m: m['metadata'].update(dbt_version='0.0.0'),
                   lambda m: m['metadata'].update(dbt_schema_version='unknown'),
                   lambda m: m['metadata'].update(adapter_type='snowflake'),
                   lambda m: m['nodes']['model.billing.fact'].update(database='PROD'),
                   lambda m: m['nodes']['seed.billing.currencies'].update(schema='PROD'),
                   lambda m: m['nodes']['model.billing.fact'].update(package_name='external'),
                   lambda m: m.update(unit_tests={'unit_test.x': {}}),
                   lambda m: m.update(functions={'function.x': {}}),
                   lambda m: m['nodes']['snapshot.billing.history'].update(original_file_path='snapshots/history.yml'),
                   lambda m: m['nodes']['model.billing.fact']['config'].update({'pre-hook': [{'sql': 'delete from prod'}]}),
                   lambda m: m['nodes']['model.billing.fact']['config'].update({'post-hook': [{'sql': 'delete from prod'}]}),
                   lambda m: m['nodes']['test.billing.grain']['config'].update(store_failures=True)]
        for change in changes:
            manifest = copy.deepcopy(self.manifest)
            change(manifest)
            if manifest['nodes']['test.billing.grain']['config'].get('store_failures'):
                manifest['nodes']['test.billing.grain']['schema'] = 'unapproved'
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.runner.validate_preflight(manifest, self.request)

    def test_explicit_execute_and_current_source_pin_required(self):
        with self.assertRaises(ValueError):
            self.run_project(execute=False)
        self.assertEqual(self.calls, [])
        (self.project / 'models/fact.sql').write_text('select 2')
        with self.assertRaises(ValueError):
            self.run_project()
        self.assertEqual(self.calls, [])

    def test_denied_preflight_never_builds(self):
        self.manifest['nodes']['model.billing.fact']['database'] = 'PROD'
        result = self.run_project()
        self.assertFalse(result['evidence_complete'])
        self.assertEqual(len(self.calls), 1)
        self.assertIn('parse', self.calls[0])
        self.assertTrue((self.output / 'run-summary.json').is_file())

    def test_failed_build_is_retained_and_source_unchanged(self):
        before = snapshot(self.project)
        result = self.run_project()
        self.assertFalse(result['evidence_complete'])
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(snapshot(self.project), before)
        self.assertTrue(any(p.read_text().find('captured output') >= 0 for p in self.output.rglob('stdout.txt')))
        for args in self.calls:
            self.assertIsInstance(args, list)
            self.assertIn('--profile', args)
            self.assertIn('--target', args)
            self.assertNotIn('--vars', args)
            self.assertNotIn('--select', args)
        self.assertFalse(list(self.output.rglob('profiles.yml')))

    def test_parse_failure_and_timeout_stop_before_build(self):
        for mode in ('failure', 'timeout'):
            self.output = self.root / mode
            calls = []
            def fail(args, **kwargs):
                calls.append(args)
                if mode == 'timeout':
                    raise subprocess.TimeoutExpired(args, 10, output=b'partial stdout', stderr=b'partial stderr')
                return subprocess.CompletedProcess(args, 2, 'partial stdout', 'partial stderr')
            result = self.run_project(process=fail)
            self.assertFalse(result['evidence_complete'])
            self.assertEqual(len(calls), 1)
            self.assertTrue(any('partial stdout' in p.read_text() for p in self.output.rglob('stdout.txt')))

    def test_profile_change_between_parse_and_build_stops_execution(self):
        def mutate(args, **kwargs):
            result = self.fake(args, **kwargs)
            self.profile_file.write_text(self.profile_file.read_text() + '\n# drift\n')
            return result
        result = self.run_project(process=mutate)
        self.assertFalse(result['evidence_complete'])
        self.assertEqual(len(self.calls), 1)

    def test_literal_profile_mismatch_and_profiles_inside_source_rejected(self):
        self.request['expected_profile']['path'] = 'wrong'
        with self.assertRaises(ValueError):
            self.run_project()
        self.assertFalse(self.calls)
        self.request['profiles_dir'] = str(self.project)
        with self.assertRaises(ValueError):
            self.run_project()

    def test_output_cannot_be_inside_project_or_reused(self):
        self.output = self.project / 'new-output'
        with self.assertRaises(ValueError):
            self.run_project()
        self.assertFalse(self.calls)
        self.output = self.root / 'existing'
        self.output.mkdir()
        with self.assertRaises((ValueError, FileExistsError)):
            self.run_project()

    def test_snowflake_profile_role_is_bound_before_process_launch(self):
        selected = {'type': 'snowflake', 'account': 'synthetic-account', 'role': 'DMA_DEV', 'warehouse': 'DMA_TEST'}
        self.profile_file.write_text(yaml.safe_dump({'qualification': {'target': 'dev', 'outputs': {'dev': selected}}}))
        self.request['adapter_type'] = 'snowflake'
        self.request['expected_profile'] = {'account': 'synthetic-account', 'role': 'WRONG_ROLE', 'warehouse': 'DMA_TEST'}
        with self.assertRaises(ValueError):
            self.run_project()
        self.assertFalse(self.calls)

    def test_project_drift_during_parse_blocks_build(self):
        def mutate(args, **kwargs):
            result = self.fake(args, **kwargs)
            (self.project / 'models/fact.sql').write_text('select 999')
            return result
        result = self.run_project(process=mutate)
        self.assertFalse(result['evidence_complete'])
        self.assertEqual(len(self.calls), 1)

    def test_environment_cannot_enable_unreviewed_failure_writes_or_selection(self):
        from unittest.mock import patch
        import os
        for name in ('DBT_STORE_FAILURES', 'DBT_SELECT', 'DBT_VARS'):
            with self.subTest(name=name), patch.dict(os.environ, {name: 'unreviewed'}):
                with self.assertRaises(ValueError):
                    self.run_project()
                self.assertFalse(self.calls)

    def test_project_global_flags_are_not_silently_applied(self):
        path = self.project / 'dbt_project.yml'
        path.write_text(path.read_text() + '\nflags:\n  store_failures: true\n')
        self.request['project_sha256'] = snapshot(self.project)['sha256']
        with self.assertRaises(ValueError):
            self.run_project()
        self.assertFalse(self.calls)
