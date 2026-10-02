"""End-to-end Tableau evidence and failure-path regression tests."""
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
SCRIPTS=ROOT/'skills/data-model-accelerator/scripts'
CASE=ROOT/'skills/data-model-accelerator/examples/tableau-omni-e2e'
sys.path.insert(0,str(SCRIPTS))
OPTIONAL=all(importlib.util.find_spec(x) for x in ('duckdb','sqlglot','pandas','yaml','lxml'))
if OPTIONAL:
    import run_tableau_omni_e2e as runner

@unittest.skipUnless(OPTIONAL,'Pinned Tableau optional engines required')
class TableauRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(prefix='dma-tableau-runner-test-');cls.out=Path(cls.tmp.name)/'run'
        cls.report=runner.run(CASE,cls.out)
    @classmethod
    def tearDownClass(cls): cls.tmp.cleanup()
    def test_complete_predeclared_replay(self):
        self.assertTrue(self.report['simulation_passed'],self.report)
        self.assertEqual(self.report['counts'],{'checks':160,'passed':160,'negative_controls':44,'worksheets':3,'valid_scenarios':16,'report_comparisons':96})
    def test_native_limits_are_not_promoted(self):
        for key in ('native_tableau_execution','native_snowflake_execution','native_omni_execution','native_dbt_compile_execution'):
            self.assertEqual(self.report[key],'unavailable')
        self.assertFalse(self.report['production_approved'])
        graph=json.loads((self.out/'source-graph.json').read_text())
        self.assertFalse(graph['workbooks'][0]['official_schema_validation']['validated'])
    def test_evidence_covers_review_categories(self):
        from verify_review_package import LOCAL_CATEGORIES
        categories={c['category'] for c in self.report['checks'] if c['status']=='pass'}
        self.assertEqual(categories,LOCAL_CATEGORIES)
    def test_negative_controls_record_intended_evidence(self):
        records={c['id']:c for c in self.report['checks']}
        for key in ('negative-source-context-order','negative-source-fixed-scope','negative-source-partition','negative-target-model-sign'):
            self.assertIn('mismatch',records[key]['evidence']['reason'].lower())
    def test_existing_output_is_never_overwritten(self):
        old=(self.out/'e2e-report.json').read_bytes()
        with self.assertRaisesRegex(ValueError,'new directory'): runner.run(CASE,self.out)
        self.assertEqual(old,(self.out/'e2e-report.json').read_bytes())
    def test_case_cannot_be_output(self):
        with self.assertRaisesRegex(ValueError,'outside the case'): runner.run(CASE,CASE/'forbidden-output')
    def test_frozen_oracle_tampering_preserves_failure_report(self):
        with tempfile.TemporaryDirectory(prefix='dma-tableau-tamper-') as d:
            case=Path(d)/'case';shutil.copytree(CASE,case)
            path=case/'expected/expected_rows.json';path.write_text(path.read_text()+' ')
            report=runner.run(case,Path(d)/'output')
            self.assertFalse(report['simulation_passed']);self.assertIn('Frozen input/oracle changed',report['fatal_error'])
            self.assertTrue((Path(d)/'output/e2e-report.json').is_file())
    def test_mismatches_cannot_be_hidden_by_totals(self):
        expected=[{'segment':'A','revenue_cents':10},{'segment':'B','revenue_cents':20}]
        changed=[{'segment':'A','revenue_cents':20},{'segment':'B','revenue_cents':10}]
        with self.assertRaisesRegex(AssertionError,'Value mismatch'): runner.compare(changed,expected)

if __name__=='__main__': unittest.main()
