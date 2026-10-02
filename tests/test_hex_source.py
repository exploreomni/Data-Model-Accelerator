"""Static Hex extraction regressions: no notebook execution."""
import importlib.util
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SKILL=Path(__file__).resolve().parents[1]/'skills/data-model-accelerator'
sys.path.insert(0,str(SKILL/'scripts'))
OPTIONAL=all(importlib.util.find_spec(x) for x in ('yaml','jsonschema','sqlglot'))
if OPTIONAL:
    import yaml
    from hex_source import inspect_repo
FIXTURE=SKILL/'examples/hex-omni-e2e/input/repo'

@unittest.skipUnless(OPTIONAL,'Optional Hex E2E dependencies are required')
class HexSourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.repo=Path(self.tmp.name)/'repo';shutil.copytree(FIXTURE,self.repo)
    def read(self,name):return yaml.safe_load((self.repo/name).read_text())
    def write(self,name,data):(self.repo/name).write_text(yaml.safe_dump(data,sort_keys=False))
    def report(self):return inspect_repo(self.repo)
    def kinds(self):return {g['kind'] for g in self.report()['gaps'] if g['severity']=='error'}
    def modify(self,name,fn):
        d=self.read(name);fn(d);self.write(name,d)
    def test_fixture_coverage_and_scoped_identity(self):
        r=self.report()
        self.assertEqual((r['counts']['projects'],r['counts']['components'],r['counts']['cells'],r['counts']['errors']),(3,1,24,0))
        self.assertTrue(r['static_coverage_complete']);self.assertFalse(r['native_runtime_validated'])
        self.assertEqual(len({c['id'] for c in r['cells']}),24)
        self.assertEqual(sum(c['label']=='Monthly summary' for c in r['cells']),3)
    def test_sql_python_chart_evidence(self):
        r=self.report()
        self.assertTrue(any(d['name']=='enriched[\'NET_CENTS\']' and 'AMOUNT_CENTS' in d['expression'] for d in r['definitions']))
        self.assertTrue(any('NULLIF' in d['expression'] for d in r['definitions']))
        self.assertTrue(any(e['kind']=='file_read' and e['from']=='file:adjustments.csv' and e['sha256'] for e in r['edges']))
        self.assertEqual(sum(e['kind']=='warehouse_read' for e in r['edges']),3)
        self.assertEqual(next(c for c in r['cells'] if c['cell_type']=='CHARTV2')['reads'],['executive_summary'])
    def test_duplicate_yaml_keys(self):
        p=self.repo/'revenue.hex.yaml';p.write_text(p.read_text()+'\nschemaVersion: 3\n')
        self.assertIn('yaml_invalid',self.kinds())
    def test_yaml_alias(self):
        (self.repo/'bad.hex.yaml').write_text('schemaVersion: 3\nmeta: &m {codeLanguage: PYTHON, title: Demo}\ncells: *m\n')
        self.assertIn('yaml_invalid',self.kinds())
    def test_schema_version(self):
        self.modify('revenue.hex.yaml',lambda d:d.update(schemaVersion=4))
        self.assertIn('schema_invalid',self.kinds())
    def test_uuid_format(self):
        self.modify('revenue.hex.yaml',lambda d:d['meta'].update(projectId='bad-id'))
        self.assertIn('schema_invalid',self.kinds())
    def test_native_type(self):
        self.modify('revenue.hex.yaml',lambda d:d['cells'][0].update(cellType='PYTHON'))
        self.assertIn('schema_invalid',self.kinds())
    def test_missing_identity(self):
        self.modify('revenue.hex.yaml',lambda d:d['meta'].pop('projectId'))
        self.assertIn('missing_identity',self.kinds())
    def test_missing_cells(self):
        self.modify('revenue.hex.yaml',lambda d:d.pop('cells'))
        self.assertIn('missing_cells',self.kinds())
    def test_omitted_referenced_cell(self):
        self.modify('revenue.hex.yaml',lambda d:d['cells'].pop(5))
        self.assertTrue({'unresolved_layout_cell','unbound_variable'}<=self.kinds())
    def test_duplicate_project(self):
        shutil.copyfile(self.repo/'revenue.hex.yaml',self.repo/'copy.hex.yaml')
        self.assertIn('duplicate_project_id',self.kinds())
    def test_duplicate_cell(self):
        self.modify('revenue.hex.yaml',lambda d:d['cells'][1].update(cellId=d['cells'][0]['cellId']))
        self.assertIn('duplicate_cell_id',self.kinds())
    def test_cell_id_in_other_project_scoped(self):
        rev=self.read('revenue.hex.yaml');ret=self.read('retention.hex.yaml')
        raw=yaml.safe_dump(ret).replace(ret['cells'][0]['cellId'],rev['cells'][0]['cellId'])
        (self.repo/'retention.hex.yaml').write_text(raw)
        self.assertNotIn('duplicate_cell_id',self.kinds())
    def test_missing_file(self):
        (self.repo/'adjustments.csv').unlink();self.assertIn('missing_file',self.kinds())
    def test_missing_component(self):
        (self.repo/'shared-revenue.hex.yaml').unlink();self.assertIn('missing_component',self.kinds())
    def test_component_version(self):
        self.modify('shared-revenue.hex.yaml',lambda d:d['meta'].update(sourceVersionId='22222222-2222-4222-8222-222222222222'))
        self.assertIn('component_version_mismatch',self.kinds())
    def test_dynamic_python_never_executes(self):
        marker=Path(self.tmp.name)/'must-not-exist'
        code='open('+repr(str(marker))+', "w").write("bad")\nx = globals()[variable_name]\n'
        self.modify('shared-revenue.hex.yaml',lambda d:d['cells'][1]['config'].update(source=code))
        self.assertIn('dynamic_python',self.kinds());self.assertFalse(marker.exists())
    def test_dynamic_file(self):
        self.modify('shared-revenue.hex.yaml',lambda d:d['cells'][1]['config'].update(source='import pandas as pd\nadjustments = pd.read_csv(file_name)\n'))
        self.assertTrue({'dynamic_python','unbound_variable'}<=self.kinds())
    def test_ambiguous_variable(self):
        self.modify('revenue.hex.yaml',lambda d:d['cells'][-1]['config'].update(source='revenue_summary = enriched\n'))
        self.assertIn('ambiguous_variable_writer',self.kinds())
    def test_self_dependent_state(self):
        self.modify('revenue.hex.yaml',lambda d:d['cells'][-1]['config'].update(source='what_if_revenue = what_if_revenue + 1\n'))
        self.assertIn('unbound_variable',self.kinds())
    def test_unqualified_namespace(self):
        self.modify('shared-revenue.hex.yaml',lambda d:d['cells'][0]['config'].update(source='SELECT * FROM INVOICE_CDC'))
        self.assertIn('unqualified_table',self.kinds())
    def test_mutation_sql(self):
        self.modify('shared-revenue.hex.yaml',lambda d:d['cells'][0]['config'].update(source='DELETE FROM DMA_HEX.RAW.INVOICE_CDC'))
        self.assertIn('parse_error',self.kinds())
    def test_dynamic_template(self):
        self.modify('revenue.hex.yaml',lambda d:d['cells'][5]['config'].update(source='SELECT * FROM {{ table_name | safe }}'))
        self.assertIn('parse_error',self.kinds())
    def test_schema_checksum(self):
        import hex_source
        old=hex_source.SCHEMA_SHA256
        try:
            hex_source.SCHEMA_SHA256='0'*64
            with self.assertRaisesRegex(ValueError,'hash mismatch'):self.report()
        finally:hex_source.SCHEMA_SHA256=old

if __name__=='__main__':unittest.main()
