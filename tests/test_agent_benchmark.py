"""Controlled synthetic attempts are checked against independently frozen SQL."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_agent_execution as execution_fixture
import agent_benchmark as benchmark
from ae_common import hash_file, hash_json

SQLGLOT = importlib.util.find_spec('sqlglot') is not None


class AgentBenchmarkTests(unittest.TestCase):
    def setUp(self):
        fixture = execution_fixture.AgentExecutionTests('test_all_missing_observations_remain_unknown')
        fixture.setUp(); self.addCleanup(fixture.doCleanups)
        self.root, self.source, self.packet = fixture.root, fixture.source, fixture.packet
        self.execution_request = fixture.request
        self.contract_path = self.root/'contract.json'
        self.contract = {'schema_version': 1, 'kind': 'authoring_contract', 'mode': 'provisional',
            'bindings': {'source_sha256': 'a'*64, 'design_sha256': 'b'*64, 'catalogue_sha256': None},
            'models': [{'id': 'count-model', 'path': 'count.sql', 'columns': ['order_count'],
                'depends_on': ['table:orders'], 'expressions': {'order_count': 'COUNT(1)'}}],
            'assumptions': [], 'provenance': []}
        self.contract_path.write_text(json.dumps(self.contract))
        self.suite = {'schema_version': 1, 'kind': 'agent_benchmark_suite', 'cases': [
            {'id': 'count-case', 'packet_sha256': fixture.request['packet_sha256'],
             'contract_path': str(self.contract_path), 'contract_sha256': hash_file(self.contract_path),
             'source_root': str(self.source), 'source_files': {'orders.sql': hash_file(self.source/'orders.sql')},
             'dialect': 'snowflake', 'paths': ['count.sql'], 'allowed_statuses': ['passed'],
             'required_findings': [{'code': 'expression_matches', 'status': 'passed', 'model_id': 'count-model'},
                                   {'code': 'dependencies_match', 'status': 'passed', 'model_id': 'count-model'}]}]}
        self.runs = {'schema_version': 1, 'kind': 'agent_benchmark_runs', 'suite_sha256': hash_json(self.suite),
            'variants': [{'id': 'baseline', 'cases': [{'id': 'count-case', 'attempts': [self.attempt('baseline-1', 1)]}]},
                         {'id': 'alternative', 'cases': [{'id': 'count-case', 'attempts':
                             [self.attempt('alternative-1', 2), self.attempt('alternative-2', 1)]}]}]}

    def attempt(self, name, count):
        root = self.root/name; root.mkdir(); (root/'count.sql').write_text(f'SELECT COUNT({count}) AS order_count FROM orders')
        request = copy.deepcopy(self.execution_request); request['run_id'] = name
        return {'artifact_root': str(root), 'execution': {'packet_dir': str(self.packet), 'request': request}}

    def compare(self):
        return benchmark.compare(self.suite, self.runs)

    @unittest.skipUnless(SQLGLOT, 'Optional SQL parser required for native SQL comparison')
    def test_real_clean_bad_and_repaired_attempts_all_count(self):
        report = self.compare(); baseline, alternative = report['variants']
        self.assertTrue(baseline['cases'][0]['first_pass_match'])
        self.assertFalse(alternative['cases'][0]['first_pass_match'])
        self.assertTrue(alternative['cases'][0]['final_match'])
        self.assertEqual(report['attempt_count'], 3); self.assertEqual(report['repair_count'], 1)
        self.assertEqual(len(alternative['cases'][0]['attempts']), 2)
        bad = alternative['cases'][0]['attempts'][0]
        self.assertIn('expression_differs', [row['code'] for row in bad['findings']])
        self.assertIn('failed', bad['disallowed_statuses'])
        self.assertEqual(bad['coverage']['findings'], len(bad['findings']))
        self.assertIsNone(bad['execution']['observed_model'])
        self.assertEqual(bad['execution']['observed_model_status'], 'unknown')
        self.assertFalse(bad['execution']['host_isolation_verified'])
        self.assertNotIn('winner', report); self.assertNotIn('recommended_model', report)

    def test_missing_required_finding_never_matches_even_if_status_allowed(self):
        self.suite['cases'][0]['allowed_statuses'] = ['passed', 'unsupported', 'not_run', 'failed']
        self.suite['cases'][0]['required_findings'] = [{'code': 'absent_check', 'status': 'passed', 'model_id': 'count-model'}]
        self.runs['suite_sha256'] = hash_json(self.suite)
        report = self.compare()
        self.assertTrue(all(not case['final_match'] for variant in report['variants'] for case in variant['cases']))

    def test_usage_categories_unknown_identity_and_host_context_remain_separate(self):
        attempts = self.runs['variants'][1]['cases'][0]['attempts']
        for index, attempt in enumerate(attempts):
            request = attempt['execution']['request']
            request.update(observed_model='observed-model', observed_effort='medium', context_mode='inherited',
                usage={'input_tokens': 100 if index else None, 'output_tokens': 10, 'cache_read_tokens': 0, 'cache_write_tokens': 5})
        report = self.compare(); alternative = report['variants'][1]
        self.assertEqual(alternative['host_reported_usage_totals'],
                         {'input_tokens': None, 'output_tokens': 20, 'cache_read_tokens': 0, 'cache_write_tokens': 10})
        self.assertEqual(alternative['usage_known_attempt_counts']['input_tokens'], 1)
        host = alternative['cases'][0]['attempts'][0]['execution']
        self.assertEqual(host['context_mode'], 'inherited'); self.assertFalse(host['usage_verified'])

    def test_no_supplied_pass_receipt_or_missing_denominator_is_accepted(self):
        original = copy.deepcopy(self.runs)
        mutations = [lambda runs: runs['variants'].pop(),
            lambda runs: runs['variants'][0]['cases'].clear(),
            lambda runs: runs['variants'][0]['cases'].append(copy.deepcopy(runs['variants'][0]['cases'][0])),
            lambda runs: runs['variants'].append(copy.deepcopy(runs['variants'][0])),
            lambda runs: runs['variants'][0]['cases'][0]['attempts'].clear(),
            lambda runs: runs['variants'][0]['cases'][0]['attempts'][0].update(passed=True),
            lambda runs: runs.update(schema_version=True)]
        for mutate in mutations:
            runs = copy.deepcopy(original); mutate(runs)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError): benchmark.compare(self.suite, runs)

    def test_empty_duplicate_or_changed_suite_is_rejected(self):
        original = copy.deepcopy(self.suite)
        mutations = [lambda suite: suite['cases'].clear(),
            lambda suite: suite['cases'].append(copy.deepcopy(suite['cases'][0])),
            lambda suite: suite['cases'][0]['required_findings'].clear(),
            lambda suite: suite['cases'][0]['paths'].append('count.sql'),
            lambda suite: suite['cases'][0]['allowed_statuses'].append('unknown'),
            lambda suite: suite['cases'][0].update(dialect='duckdb')]
        for mutate in mutations:
            suite = copy.deepcopy(original); mutate(suite)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError): benchmark.compare(suite, self.runs)

    def test_changed_contract_source_or_packet_is_rejected(self):
        for path in (self.contract_path, self.source/'orders.sql', self.packet/'TASK.md'):
            original = path.read_bytes(); path.write_bytes(original+b'\n')
            with self.subTest(path=path.name), self.assertRaises(ValueError): self.compare()
            path.write_bytes(original)

    def test_missing_candidate_or_unfrozen_source_evidence_fails(self):
        candidate = Path(self.runs['variants'][0]['cases'][0]['attempts'][0]['artifact_root'])/'count.sql'
        candidate.unlink()
        with self.assertRaises(ValueError): self.compare()
        candidate.write_text('SELECT COUNT(1) AS order_count FROM orders')
        self.contract['provenance'] = [{'source': {'path': 'unfrozen.sql', 'sha256': 'a'*64}}]
        self.contract_path.write_text(json.dumps(self.contract))
        self.suite['cases'][0]['contract_sha256'] = hash_file(self.contract_path)
        self.runs['suite_sha256'] = hash_json(self.suite)
        with self.assertRaises(ValueError): self.compare()

    def test_packet_identity_and_duplicate_host_run_cannot_be_relabelled(self):
        self.suite['cases'][0]['packet_sha256'] = 'a'*64; self.runs['suite_sha256'] = hash_json(self.suite)
        with self.assertRaises(ValueError): self.compare()
        self.suite['cases'][0]['packet_sha256'] = self.execution_request['packet_sha256']
        self.runs['suite_sha256'] = hash_json(self.suite)
        self.runs['variants'][1]['cases'][0]['attempts'][0]['execution']['request']['run_id'] = 'baseline-1'
        with self.assertRaises(ValueError): self.compare()

    def test_source_change_during_evaluation_is_rejected(self):
        original = benchmark.evaluate
        def changed(*args, **kwargs):
            receipt = original(*args, **kwargs)
            (self.source/'orders.sql').write_text('select changed from orders')
            return receipt
        with patch.object(benchmark, 'evaluate', side_effect=changed), self.assertRaises(ValueError): self.compare()

    def test_safe_paths_reject_source_escape_and_symlink(self):
        self.suite['cases'][0]['source_files'] = {'../outside.sql': 'a'*64}
        self.runs['suite_sha256'] = hash_json(self.suite)
        with self.assertRaises(ValueError): self.compare()
        self.suite['cases'][0]['source_files'] = {'orders.sql': hash_file(self.source/'orders.sql')}
        target = self.root/'contract-link.json'; target.symlink_to(self.contract_path)
        self.suite['cases'][0]['contract_path'] = str(target); self.runs['suite_sha256'] = hash_json(self.suite)
        with self.assertRaises(ValueError): self.compare()

    @unittest.skipUnless(SQLGLOT, 'Optional SQL parser required for CLI rubric match')
    def test_cli_pass_mismatch_and_clean_block_exit_codes(self):
        suite_path, runs_path = self.root/'suite.json', self.root/'runs.json'
        suite_path.write_text(json.dumps(self.suite)); runs_path.write_text(json.dumps(self.runs))
        def run(name):
            return subprocess.run([sys.executable, str(Path(benchmark.__file__)), '--suite', str(suite_path),
                '--runs', str(runs_path), '--output', str(self.root/name)], capture_output=True, text=True)
        good = run('report.json'); self.assertEqual(good.returncode, 0, good.stderr)
        self.assertTrue(json.loads(good.stdout)['all_final_rubrics_match'])
        self.assertEqual(run('report.json').returncode, 2)
        self.runs['variants'][1]['cases'][0]['attempts'].pop(); runs_path.write_text(json.dumps(self.runs))
        mismatch = run('mismatch.json'); self.assertEqual(mismatch.returncode, 1, mismatch.stderr)
        self.assertFalse(json.loads(mismatch.stdout)['all_final_rubrics_match'])
        self.runs['suite_sha256'] = 'a'*64; runs_path.write_text(json.dumps(self.runs))
        blocked = run('blocked.json'); self.assertEqual(blocked.returncode, 2)
        self.assertFalse((self.root/'blocked.json').exists()); self.assertNotIn('Traceback', blocked.stderr)


if __name__ == '__main__': unittest.main()
