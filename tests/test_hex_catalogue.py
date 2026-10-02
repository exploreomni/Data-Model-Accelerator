"""Synthetic catalogue metadata and source-binding regression tests."""
import copy
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SKILL=Path(__file__).resolve().parents[1]/'skills/data-model-accelerator'
sys.path.insert(0,str(SKILL/'scripts'))
OPTIONAL=all(importlib.util.find_spec(x) for x in ('yaml','jsonschema','sqlglot','duckdb','pandas'))
if OPTIONAL:
    from hex_catalogue import build_catalogue, normalize_receipts, _ddl_columns
CASE=SKILL/'examples/hex-omni-e2e'

@unittest.skipUnless(OPTIONAL,'Optional Hex E2E dependencies are required')
class HexCatalogueTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.case=Path(self.tmp.name)/'case';self.case.mkdir()
        shutil.copytree(CASE/'input',self.case/'input')
        shutil.copytree(CASE/'target/snowflake',self.case/'target/snowflake')
        self.out=Path(self.tmp.name)/'output'
    def build(self):return build_catalogue(self.case,self.out,'a'*64)
    def read(self,path):return json.loads((self.case/path).read_text())
    def write(self,path,value):(self.case/path).write_text(json.dumps(value,indent=2)+'\n')
    def native(self):
        return self.read('input/catalogue/exports/objects.json')['rows'],self.read('input/catalogue/exports/columns.json')['rows'],_ddl_columns(self.case)
    def test_complete_four_object_twenty_three_column_binding(self):
        r=self.build();v=r['verification']
        self.assertTrue(v['catalogue_context_complete']);self.assertEqual(v['counts']['objects'],4)
        self.assertEqual(v['counts']['columns'],23);self.assertEqual(v['counts']['resolved_references'],4)
        self.assertEqual(v['source_snapshot_sha256'],'a'*64)
        cat=json.loads(Path(r['catalogue_path']).read_text());bind=json.loads(Path(r['bindings_path']).read_text())
        self.assertTrue(all(c['nullable'] is True for o in cat['objects'] for c in o['columns']))
        invoice=next(o for o in cat['objects'] if o['identity']['name']=='INVOICE_CDC')
        self.assertEqual(next(c for c in invoice['columns'] if c['path']==['INVOICE_DATE'])['data_type'],'VARCHAR')
        kinds=[x['source_kind'] for x in bind['references']]
        self.assertEqual(kinds.count('hex_warehouse_query'),3);self.assertEqual(kinds.count('proposed_governed_csv_landing'),1)
    def test_pinned_receipts_not_retimestamped(self):
        before=(self.case/'input/catalogue/exports/objects.json').read_bytes();r=self.build()
        self.assertEqual(before,(self.out/'exports/objects.json').read_bytes())
        self.assertEqual(before,(self.case/'input/catalogue/exports/objects.json').read_bytes())
        cat=json.loads(Path(r['catalogue_path']).read_text())
        self.assertEqual(cat['source_receipt_captured_at'],json.loads(before)['captured_at'])
    def test_missing_raw_column(self):
        raw=self.read('input/raw-data.json');raw['INVOICE_CDC'][0].pop('CUSTOMER_ID');self.write('input/raw-data.json',raw)
        with self.assertRaisesRegex(ValueError,'Raw fixture column inventory'):self.build()
    def test_changed_raw_value_type(self):
        raw=self.read('input/raw-data.json');raw['INVOICE_CDC'][0]['AMOUNT_CENTS']='12000';self.write('input/raw-data.json',raw)
        with self.assertRaisesRegex(ValueError,'Raw integer value'):self.build()
    def test_export_hash_mutation(self):
        p=self.case/'input/catalogue/exports/columns.json';p.write_text(p.read_text()+'\n')
        with self.assertRaisesRegex(ValueError,'Pinned synthetic export hash'):self.build()
    def test_missing_native_column(self):
        objects,columns,ddl=self.native();columns.pop()
        with self.assertRaisesRegex(ValueError,'does not exactly match'):normalize_receipts(objects,columns,ddl)
    def test_native_type_null_and_case_mismatches(self):
        objects,columns,ddl=self.native()
        for field,value in [('DATA_TYPE','BOOLEAN'),('IS_NULLABLE','NO'),('COLUMN_NAME','tenant_id')]:
            with self.subTest(field=field):
                changed=copy.deepcopy(columns);changed[0][field]=value
                with self.assertRaisesRegex(ValueError,'does not exactly match'):normalize_receipts(objects,changed,ddl)
    def test_wrong_account(self):
        data=self.read('input/catalogue/provenance.json');data['context']['platform_instance']='OTHER_ACCOUNT';self.write('input/catalogue/provenance.json',data)
        with self.assertRaisesRegex(ValueError,'account/connection context'):self.build()
    def test_unknown_physical_graph_binding(self):
        p=self.case/'input/repo/shared-revenue.hex.yaml';p.write_text(p.read_text().replace('DMA_HEX.RAW.INVOICE_CDC','DMA_HEX.RAW.UNKNOWN_INVOICE'))
        with self.assertRaisesRegex(ValueError,'Unknown/unapproved Hex warehouse source binding'):self.build()
    def test_bootstrap_type_drift(self):
        p=self.case/'target/snowflake/00_raw_contract.sql';p.write_text(p.read_text().replace('AMOUNT_CENTS NUMBER(38,0)','AMOUNT_CENTS VARCHAR'))
        with self.assertRaisesRegex(ValueError,'does not exactly match'):self.build()
    def test_source_hash_required(self):
        with self.assertRaisesRegex(ValueError,'source snapshot SHA'):build_catalogue(self.case,self.out,'not-a-hash')
    def test_csv_column_loss(self):
        p=self.case/'input/repo/adjustments.csv';p.write_text(p.read_text().replace(',REASON',''))
        with self.assertRaisesRegex(ValueError,'CSV column inventory'):self.build()
    def test_header_only_adjustments_preserves_metadata_and_binding(self):
        p=self.case/'input/repo/adjustments.csv'
        p.write_text('TENANT_ID,INVOICE_ID,ADJUSTMENT_CENTS,REASON\n')
        result=self.build()
        self.assertTrue(result['verification']['catalogue_context_complete'])
        catalogue=json.loads(Path(result['catalogue_path']).read_text())
        bindings=json.loads(Path(result['bindings_path']).read_text())
        self.assertEqual(catalogue['input_evidence']['row_counts']['ADJUSTMENTS'],0)
        adjustment=next(o for o in catalogue['objects'] if o['identity']['name']=='ADJUSTMENTS')
        self.assertEqual([c['path'][0] for c in adjustment['columns']],['TENANT_ID','INVOICE_ID','ADJUSTMENT_CENTS','REASON'])
        landing=next(r for r in bindings['references'] if r['source_kind']=='proposed_governed_csv_landing')
        self.assertEqual(landing['status'],'resolved')
        self.assertEqual(landing['source_file_sha256'],catalogue['input_evidence']['csv_sha256'])
    def test_other_empty_raw_tables_remain_unsupported(self):
        raw=self.read('input/raw-data.json');raw['INVOICE_CDC']=[];self.write('input/raw-data.json',raw)
        with self.assertRaisesRegex(ValueError,'Empty or missing synthetic raw table: INVOICE_CDC'):self.build()

if __name__=='__main__':unittest.main()
