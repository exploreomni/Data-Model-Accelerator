"""Hex evidence denominators, independent expectations and actual schema coverage."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

SCRIPTS=Path(__file__).resolve().parents[1]/'skills/data-model-accelerator/scripts'
sys.path.insert(0,str(SCRIPTS))
try:
    import run_hex_omni_e2e as runner
    import hex_execution as execution
except ImportError:
    runner=execution=None
CASE=SCRIPTS.parent/'examples/hex-omni-e2e'

@unittest.skipIf(runner is None,'Optional Hex E2E dependencies absent')
class HexRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='dma-hex-runner-test-')
        self.root=Path(self.temp.name);self.case=self.root/'case'
        shutil.copytree(CASE,self.case,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    def tearDown(self):self.temp.cleanup()
    def rewrite_plan(self,fn):
        path=self.case/'test-plan.json';value=json.loads(path.read_text());fn(value);path.write_text(json.dumps(value))
    def test_complete_three_project_run_covers_every_predeclared_check(self):
        result=runner.run(self.case,self.root/'run')
        self.assertTrue(result['simulation_passed'],result)
        expected=runner.load_plan(self.case)['required_test_ids']
        self.assertEqual(set(expected),{c['id'] for c in result['checks']})
        self.assertEqual(result['counts']['projects'],3)
        self.assertGreater(result['counts']['negative_controls'],20)
    def test_removed_expected_pin_rejected(self):
        self.rewrite_plan(lambda p:p['frozen_input_hashes'].pop('expected/expected_rows.json'))
        with self.assertRaisesRegex(ValueError,'pin inventory'):runner.load_plan(self.case)
    def test_expected_rows_cannot_be_replaced_to_make_candidate_pass(self):
        p=self.case/'expected/expected_rows.json';value=json.loads(p.read_text());value['invoices'][0]['net_cents']+=1;p.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError,'Frozen independent'):runner.load_plan(self.case)
    def test_duplicated_check_is_not_extra_coverage(self):
        self.rewrite_plan(lambda p:p['required_test_ids'].append(p['required_test_ids'][0]))
        with self.assertRaisesRegex(ValueError,'duplicated'):runner.load_plan(self.case)
    def test_missing_native_cell_cannot_report_complete(self):
        self.rewrite_plan(lambda p:p['native_cell_ids'].append('declared-but-missing/cell'))
        result=runner.run(self.case,self.root/'run')
        self.assertFalse(result['simulation_passed'])
        self.assertIn('native-cell-coverage',result['failures'])
    def test_output_cannot_replace_existing_evidence(self):
        output=self.root/'run';output.mkdir();(output/'evidence.json').write_text('preserve')
        with self.assertRaisesRegex(ValueError,'new directory'):runner.run(self.case,output)
        self.assertEqual((output/'evidence.json').read_text(),'preserve')
    def test_self_consistent_dictionary_omission_detected_against_built_schema(self):
        folder=self.case/'documentation';ipath=folder/'model-inventory.json';dpath=folder/'data-dictionary.json'
        inv=json.loads(ipath.read_text());dct=json.loads(dpath.read_text());model=inv['models'][0];column=model['columns'].pop()
        documented=next(m for m in dct['models'] if m['model_id']==model['model_id'])
        documented['columns']=[c for c in documented['columns'] if c['name']!=column]
        ipath.write_text(json.dumps(inv));dct['model_inventory_sha256']=hashlib.sha256(ipath.read_bytes()).hexdigest();dpath.write_text(json.dumps(dct))
        raw,adj=execution.load_inputs(self.case)
        with execution.connection(raw,adj) as con:
            execution.build_models(con,self.case/'target/dbt')
            with self.assertRaisesRegex(AssertionError,'column mismatch'):runner.validate_documentation(self.case,con)

if __name__=='__main__':unittest.main()
