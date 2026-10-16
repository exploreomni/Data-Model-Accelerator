"""Pure capability/identity/argv contracts; these tests never execute dbt."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'
sys.path.insert(0, str(SCRIPTS))
import dbt_runtime as runtime


class RuntimeContractTests(unittest.TestCase):
    def test_defaults_and_no_discovery_execution(self):
        with patch('subprocess.run', side_effect=AssertionError('discovery executed')):
            for distribution, mode in [('dbt_core', 'none'), ('dbt', 'baseline'), ('dbt_oss', 'none')]:
                selection = runtime.validate_selection({'distribution': distribution, 'version': runtime.PINNED_VERSIONS[distribution]})
                self.assertEqual(selection['analysis_mode'], mode)
                self.assertEqual(selection['features'], [])
                contract = runtime.runtime_contract(selection, 'duckdb')
                self.assertFalse(contract['probe_performed'])
                self.assertTrue(contract['qualification']['qualified'])
                self.assertEqual(set(contract['features']), set(runtime.FEATURES))
                json.dumps(contract, allow_nan=False)

    def test_invalid_selection_never_silently_defaults(self):
        cases = [None, {}, {'distribution': 'fusion', 'version': '2.0.8'},
                 {'distribution': 'dbt', 'version': 'latest'}, {'distribution': 'dbt', 'version': '>=2'},
                 {'distribution': 'dbt', 'version': '2.0.8', 'warehouse': 'duckdb'},
                 {'distribution': 'dbt', 'version': '2.0.8', 'features': ['checks', 'checks']},
                 {'distribution': 'dbt', 'version': '2.0.8', 'features': [{}]},
                 {'distribution': 'dbt', 'version': '2.0.8', 'analysis_mode': True}]
        for value in cases:
            with self.subTest(value=value), self.assertRaises(ValueError):
                runtime.validate_selection(value)

    def test_documentation_never_promotes_unknown_version_mode_or_features(self):
        for patch_value in ({'version': '2.0.9'}, {'analysis_mode': 'strict'}, {'features': ['checks']}):
            selection = dict(distribution='dbt', version='2.0.8', **{})
            selection.update(patch_value)
            self.assertFalse(runtime.runtime_contract(selection, 'duckdb')['execution']['qualified'])
        oss = runtime.runtime_contract({'distribution': 'dbt_oss', 'version': '2.0.8'}, 'duckdb')
        self.assertFalse(oss['features']['native_lint']['documented'])
        self.assertFalse(oss['features']['sql_analysis']['documented'])
        self.assertTrue(runtime.runtime_contract({'distribution': 'dbt_core', 'version': '1.12.4'})['features']['dbt_state']['documented'])
        for warehouse in ('snowflake', 'clickhouse', 'motherduck', 'databricks', 'bigquery', 'redshift'):
            self.assertFalse(runtime.runtime_contract({'distribution': 'dbt', 'version': '2.0.8'}, warehouse)['execution']['qualified'])
        self.assertEqual(runtime.runtime_contract({'distribution': 'dbt', 'version': '2.0.8'}, 'clickhouse')['adapter_lifecycle'], 'Private beta')

    def test_exact_engine_command_contract(self):
        args = [Path('/runtime/dbt'), 'build', Path('/copy'), Path('/profiles'), 'p', 'dev', Path('/out')]
        core = runtime.runtime_argv(*args, {'distribution': 'dbt_core', 'version': '1.12.4'})
        self.assertIn('--no-partial-parse', core)
        for dist, mode in [('dbt', 'baseline'), ('dbt_oss', 'off')]:
            selection = {'distribution': dist, 'version': '2.0.8'}
            build = runtime.runtime_argv(*args, selection)
            self.assertNotIn('--no-partial-parse', build)
            self.assertEqual(build[build.index('--static-analysis') + 1], mode)
            args[1] = 'parse'
            self.assertNotIn('--static-analysis', runtime.runtime_argv(*args, selection))
            args[1] = 'build'
        with self.assertRaises(ValueError):
            runtime.runtime_argv(args[0], 'run-operation', *args[2:], {'distribution': 'dbt', 'version': '2.0.8'})

    def test_version_label_disambiguates_identical_artifact_version(self):
        for dist, label in [('dbt', 'dbt'), ('dbt_oss', 'dbt-oss')]:
            selected = {'distribution': dist, 'version': '2.0.8'}
            self.assertEqual(runtime.observed_version(label + ' 2.0.8\n', selected)['distribution'], dist)
            for value in ('dbt 2.0.9', 'dbt-core 2.0.8', '2.0.8', 'dbt 2.0.8\nextra'):
                with self.assertRaises(ValueError):
                    runtime.observed_version(value, selected)

    def test_wheel_identity_is_read_only_and_covers_implementation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            (root / 'bin').mkdir()
            site = root / 'lib/python3.12/site-packages'
            (site / 'dbt').mkdir(parents=True)
            (site / 'dbt-2.0.8.dist-info').mkdir()
            (site / 'dbt-2.0.8.dist-info/METADATA').write_text('Name: dbt\nVersion: 2.0.8\n')
            (site / 'dbt/_core.abi3.so').write_bytes(b'synthetic-not-executable')
            (site / 'dbt/__init__.py').write_text('raise RuntimeError("must not import")')
            (root / 'pyvenv.cfg').write_text('synthetic')
            (root / 'bin/python').write_bytes(b'synthetic-interpreter')
            executable = root / 'bin/dbt'
            executable.write_text('#!' + str(root / 'bin/python') + '\n')
            selection = {'distribution': 'dbt', 'version': '2.0.8'}
            with patch('subprocess.run', side_effect=AssertionError('identity executed')):
                before = runtime.runtime_identity(executable, selection)
                (site / 'dbt/_core.abi3.so').write_bytes(b'changed')
                self.assertNotEqual(before, runtime.runtime_identity(executable, selection))
            with self.assertRaises((ValueError, OSError)):
                runtime.runtime_identity(executable, {'distribution': 'dbt_oss', 'version': '2.0.8'})

    def test_platform_driver_contract_is_exact_and_no_motherduck_inference(self):
        for system, machine in [('Darwin', 'arm64'), ('Linux', 'x86_64')]:
            contract = runtime.driver_contract(system, machine)
            self.assertEqual(contract['version'], '1.5.4')
            self.assertRegex(contract['sha256'], r'^[0-9a-f]{64}$')
            self.assertEqual(contract['adapter'], 'duckdb')
        with self.assertRaises(ValueError):
            runtime.driver_contract('Windows', 'arm64')


if __name__ == '__main__':
    unittest.main()
