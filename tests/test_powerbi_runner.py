"""Review evidence, immutable inputs and actual Power BI replay regression."""
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
CASE=ROOT/'skills/data-model-accelerator/examples/powerbi-omni-e2e'
sys.path.insert(0,str(ROOT/'skills/data-model-accelerator/scripts'))
OPTIONAL=all(importlib.util.find_spec(m) for m in ('duckdb','sqlglot','pandas','yaml','jsonschema','referencing'))
if OPTIONAL: import run_powerbi_omni_e2e as runner


@unittest.skipUnless(OPTIONAL,'Pinned optional Power BI engines required')
class PowerBIRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(prefix='dma-powerbi-runner-');cls.out=Path(cls.tmp.name)/'run';cls.report=runner.run(CASE,cls.out)
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def test_complete_declared_replay(self):
        self.assertTrue(self.report['simulation_passed'],self.report)
        self.assertEqual(self.report['check_count'],212);self.assertEqual(self.report['negative_control_count'],61)
        self.assertEqual([c['id'] for c in self.report['checks']],json.loads((CASE/'test-plan.json').read_text())['required_test_ids'])
    def test_expected_denial_reasons_and_native_limits(self):
        records={c['id']:c for c in self.report['checks']}
        self.assertIn('access denied',records['source-denied-role_mismatch']['evidence']['reason'])
        self.assertIn('date window',records['target-denied-reversed_dates']['evidence']['reason'])
        for key in ('native_powerbi_execution','native_snowflake_execution','native_omni_execution','native_dbt_compile_execution'):self.assertEqual(self.report[key],'unavailable')
        self.assertFalse(self.report['production_approved'])
    def test_actual_schema_validation_separate_from_native_runtime(self):
        graph=json.loads((self.out/'source-graph.json').read_text());self.assertEqual(graph['counts']['schema_validated_files'],10)
        self.assertIn('native_runtime_unverified',{g['kind'] for g in graph['gaps']})
    def test_review_category_coverage(self):
        from verify_review_package import LOCAL_CATEGORIES
        self.assertEqual({c['category'] for c in self.report['checks']},LOCAL_CATEGORIES)
    def test_output_never_overwrites_evidence_or_inputs(self):
        before=(self.out/'e2e-report.json').read_bytes()
        for path in (self.out,CASE/'forbidden-output'):
            with self.assertRaises(ValueError):runner.run(CASE,path)
        self.assertEqual(before,(self.out/'e2e-report.json').read_bytes())
    def test_frozen_oracle_tamper_has_persisted_failure(self):
        with tempfile.TemporaryDirectory(prefix='dma-powerbi-tamper-') as d:
            clone=Path(d)/'case';shutil.copytree(CASE,clone);path=clone/'expected/expected_rows.json';path.write_text(path.read_text()+' ')
            out=Path(d)/'out';report=runner.run(clone,out)
            self.assertFalse(report['simulation_passed']);self.assertIn('Frozen input/oracle changed',report['runner_error']);self.assertTrue((out/'e2e-report.json').exists())
    def test_matching_totals_do_not_hide_slice_errors_or_blank_coercion(self):
        for actual,want in [([{'revenue_cents':10},{'revenue_cents':20}],[{'revenue_cents':20},{'revenue_cents':10}]),([{'payment_rate':0}],[{'payment_rate':None}])]:
            with self.assertRaises(AssertionError):runner.compare(actual,want)


if __name__=='__main__':unittest.main()
