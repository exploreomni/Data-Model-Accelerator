"""Synthetic Tableau metadata, source identity, and incomplete-evidence regressions."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

SKILL=Path(__file__).resolve().parents[1]/'skills/data-model-accelerator'
sys.path.insert(0,str(SKILL/'scripts'))
OPTIONAL=all(importlib.util.find_spec(name) for name in ('yaml','sqlglot','duckdb','pandas'))
if OPTIONAL:
    from tableau_catalogue import build_catalogue, normalize_receipts, _ddl_columns, PINNED_EXPORTS
    from verify_catalogue import verify
CASE=SKILL/'examples/tableau-omni-e2e'


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@unittest.skipUnless(OPTIONAL,'Optional Tableau E2E dependencies are required')
class TableauCatalogueTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.case=Path(self.tmp.name)/'case'
        shutil.copytree(CASE/'input',self.case/'input')
        shutil.copytree(CASE/'target/snowflake',self.case/'target/snowflake')
        self.out=Path(self.tmp.name)/'output'

    def build(self): return build_catalogue(self.case,self.out,'a'*64)
    def read(self,path): return json.loads((self.case/path).read_text())
    def write(self,path,value): (self.case/path).write_text(json.dumps(value,indent=2)+'\n')
    def native(self):
        return self.read('input/catalogue/exports/objects.json')['rows'],self.read('input/catalogue/exports/columns.json')['rows'],_ddl_columns(self.case)

    def change_sources(self,before,after):
        """Keep the TDS mirror consistent so tests reach catalogue-level binding."""
        for name in ('billing.twb','billing.tds'):
            path=self.case/'input/repo'/name
            content=path.read_text();self.assertIn(before,content)
            path.write_text(content.replace(before,after))

    def output_json(self,result):
        return json.loads(Path(result['catalogue_path']).read_text()),json.loads(Path(result['bindings_path']).read_text())

    def verify_changed_output(self,result,catalogue,bindings):
        """Rebind the changed JSON hash so omissions are not merely hash failures."""
        path=Path(result['catalogue_path']);path.write_text(json.dumps(catalogue,indent=2)+'\n')
        bindings['catalogue_sha256']=sha(path)
        Path(result['bindings_path']).write_text(json.dumps(bindings,indent=2)+'\n')
        return verify(path,Path(result['bindings_path']))

    def test_complete_four_objects_twenty_three_physical_columns(self):
        result=self.build();report=result['verification'];catalogue,bindings=self.output_json(result)
        self.assertTrue(report['catalogue_context_complete'])
        self.assertEqual((report['counts']['objects'],report['counts']['columns'],report['counts']['resolved_references']),(4,23,4))
        self.assertEqual(report['source_snapshot_sha256'],'a'*64)
        self.assertEqual(catalogue['origin'],'synthetic')
        self.assertFalse(report['native_metadata_consistency']['native_warehouse_execution'])
        self.assertTrue(all(column['nullable'] is True for obj in catalogue['objects'] for column in obj['columns']))
        invoice=next(obj for obj in catalogue['objects'] if obj['identity']['name']=='INVOICE_CDC')
        self.assertEqual(next(c for c in invoice['columns'] if c['path']==['INVOICE_DATE'])['data_type'],'VARCHAR')
        self.assertEqual(next(c for c in invoice['columns'] if c['path']==['AMOUNT_CENTS'])['data_type'],'NUMBER(38,0)')
        self.assertTrue(all(set(obj['metadata_status'].values())=={'unknown'} for obj in catalogue['objects']))
        self.assertTrue(all(ref['namespace']=={'platform_instance':'DMA_TABLEAU_SYNTHETIC','catalog':'DMA_TABLEAU','schema':'RAW'} for ref in bindings['references']))

    def test_proposed_csv_landing_is_currently_hash_bound_not_deployment_or_column_lineage(self):
        catalogue,bindings=self.output_json(self.build())
        self.assertEqual([ref['source_kind'] for ref in bindings['references']].count('tableau_custom_sql'),3)
        landings=[ref for ref in bindings['references'] if ref['source_kind']=='proposed_governed_csv_landing']
        self.assertEqual(len(landings),1);landing=landings[0]
        self.assertEqual(landing['source_file_path'],'adjustments.csv')
        self.assertEqual(landing['source_file_sha256'],sha(self.case/'input/repo/adjustments.csv'))
        self.assertEqual(landing['source_file_sha256'],catalogue['input_evidence']['csv_sha256'])
        self.assertIn('not an existing deployed table',landing['evidence'])
        self.assertTrue(all('not expression-level column lineage' in ref['column_binding_basis'] for ref in bindings['references']))
        adjustment=next(obj for obj in catalogue['objects'] if obj['identity']['name']=='ADJUSTMENTS')
        self.assertEqual(adjustment['lifecycle'],'proposed_governed_csv_landing')

    def test_current_twb_tds_csv_hashes_are_retained_without_tds_duplicate_authority(self):
        # Harmless byte changes must bind to the current parsed files, not old pins.
        for name in ('billing.twb','billing.tds'):
            path=self.case/'input/repo'/name;path.write_bytes(path.read_bytes()+b'\n')
        _,bindings=self.output_json(self.build())
        assets={asset['path']:asset for asset in bindings['source_assets']}
        self.assertEqual(set(assets),{'billing.twb','billing.tds','adjustments.csv'})
        for name,asset in assets.items(): self.assertEqual(asset['sha256'],sha(self.case/'input/repo'/name))
        self.assertEqual(len(bindings['references']),4)
        self.assertTrue(all('billing.twb#' in ref['source_reference'] for ref in bindings['references']))
        self.assertTrue(all('billing.tds' not in ref['source_reference'] for ref in bindings['references']))
        self.assertIn('Caller supplies canonical inventory hash',bindings['source_snapshot_binding_note'])

    def test_pinned_receipts_are_preserved_with_original_capture_time(self):
        before={relative:(self.case/'input/catalogue'/relative).read_bytes() for relative in PINNED_EXPORTS}
        catalogue,_=self.output_json(self.build())
        for relative,data in before.items():
            self.assertEqual((self.out/relative).read_bytes(),data)
            self.assertEqual((self.case/'input/catalogue'/relative).read_bytes(),data)
            self.assertEqual(sha(self.out/relative),PINNED_EXPORTS[relative])
            self.assertEqual(json.loads(data)['captured_at'],catalogue['source_receipt_captured_at'])
        self.assertIn('no warehouse query',catalogue['capture_basis'])

    def test_source_account_drift_rejected_even_when_tds_matches(self):
        self.change_sources('server="DMA_TABLEAU_SYNTHETIC"','server="OTHER_ACCOUNT"')
        with self.assertRaisesRegex(ValueError,'source connection/account/catalog/schema binding'): self.build()

    def test_source_connection_id_drift_rejected_even_when_relation_and_tds_match(self):
        self.change_sources('tableau-billing-snowflake','tableau-other-connection')
        with self.assertRaisesRegex(ValueError,'source connection/account/catalog/schema binding'): self.build()

    def test_source_declared_catalog_and_schema_drift_rejected(self):
        for before,after in [('dbname="DMA_TABLEAU"','dbname="OTHER_DATABASE"'),('schema="RAW"','schema="OTHER_SCHEMA"')]:
            with self.subTest(attribute=before):
                self.change_sources(before,after)
                with self.assertRaisesRegex(ValueError,'source connection/account/catalog/schema binding'): self.build()
                self.change_sources(after,before)

    def test_source_relation_connection_must_resolve(self):
        self.change_sources('connection="tableau-billing-snowflake"','connection="missing-connection"')
        with self.assertRaisesRegex(ValueError,'source graph has unresolved static errors'): self.build()

    def test_wrong_provenance_account_connection_or_namespace(self):
        original=self.read('input/catalogue/provenance.json')
        for field in ('platform_instance','connection_id','catalog','schema','location'):
            with self.subTest(field=field):
                changed=copy.deepcopy(original);changed['context'][field]='OTHER'
                self.write('input/catalogue/provenance.json',changed)
                with self.assertRaisesRegex(ValueError,'provenance/account/connection context'): self.build()

    def test_changed_native_export_or_replacement_pin_is_rejected(self):
        path=self.case/'input/catalogue/exports/columns.json';path.write_bytes(path.read_bytes()+b'\n')
        with self.assertRaisesRegex(ValueError,'Pinned synthetic export hash mismatch'): self.build()
        provenance=self.read('input/catalogue/provenance.json')
        provenance['exports']['exports/columns.json']=sha(path);self.write('input/catalogue/provenance.json',provenance)
        with self.assertRaisesRegex(ValueError,'pins differ from the reviewed synthetic receipts'): self.build()

    def test_missing_native_object_or_column(self):
        objects,columns,ddl=self.native()
        with self.assertRaisesRegex(ValueError,'Native object inventory incomplete'): normalize_receipts(objects[:-1],columns,ddl)
        with self.assertRaisesRegex(ValueError,'does not exactly match'): normalize_receipts(objects,columns[:-1],ddl)

    def test_native_column_type_null_name_and_ordinal_drift(self):
        objects,columns,ddl=self.native()
        for field,value in [('DATA_TYPE','BOOLEAN'),('IS_NULLABLE','NO'),('COLUMN_NAME','tenant_id'),('ORDINAL_POSITION',2)]:
            with self.subTest(field=field):
                changed=copy.deepcopy(columns);changed[0][field]=value
                with self.assertRaises(ValueError): normalize_receipts(objects,changed,ddl)
        numeric=next(i for i,column in enumerate(columns) if column['DATA_TYPE']=='NUMBER')
        for field,value in [('NUMERIC_PRECISION',20),('NUMERIC_SCALE',2),('NUMERIC_PRECISION',None)]:
            with self.subTest(numeric_field=field,value=value):
                changed=copy.deepcopy(columns);changed[numeric][field]=value
                with self.assertRaises(ValueError): normalize_receipts(objects,changed,ddl)

    def test_native_fields_namespaces_types_and_duplicates_are_not_silently_normalized(self):
        objects,columns,ddl=self.native()
        for field,value in [('TABLE_CATALOG','OTHER'),('TABLE_SCHEMA','OTHER'),('TABLE_NAME','invoice_cdc'),('TABLE_TYPE','VIEW')]:
            with self.subTest(object_field=field):
                changed=copy.deepcopy(objects);changed[0][field]=value
                with self.assertRaises(ValueError): normalize_receipts(changed,columns,ddl)
        changed=copy.deepcopy(columns);changed[0]['TABLE_SCHEMA']='OTHER'
        with self.assertRaisesRegex(ValueError,'Native column namespace mismatch'): normalize_receipts(objects,changed,ddl)
        changed=copy.deepcopy(columns);changed[0].pop('IS_NULLABLE')
        with self.assertRaisesRegex(ValueError,'metadata shape mismatch'): normalize_receipts(objects,changed,ddl)
        with self.assertRaisesRegex(ValueError,'Duplicate native column'): normalize_receipts(objects,columns+[columns[0]],ddl)

    def test_bootstrap_type_and_nullability_drift(self):
        path=self.case/'target/snowflake/00_raw_contract.sql';original=path.read_text()
        for replacement in ('AMOUNT_CENTS VARCHAR','AMOUNT_CENTS NUMBER(38,0) NOT NULL'):
            with self.subTest(replacement=replacement):
                self.assertIn('AMOUNT_CENTS NUMBER(38,0)',original)
                path.write_text(original.replace('AMOUNT_CENTS NUMBER(38,0)',replacement))
                with self.assertRaisesRegex(ValueError,'does not exactly match'): self.build()

    def test_missing_raw_column_and_invalid_scalar_type(self):
        original=self.read('input/raw-data.json')
        changed=copy.deepcopy(original);changed['INVOICE_CDC'][0].pop('CUSTOMER_ID');self.write('input/raw-data.json',changed)
        with self.assertRaisesRegex(ValueError,'Raw fixture column inventory mismatch'): self.build()
        changed=copy.deepcopy(original);changed['INVOICE_CDC'][0]['AMOUNT_CENTS']='12000';self.write('input/raw-data.json',changed)
        with self.assertRaisesRegex(ValueError,'Raw integer value required'): self.build()

    def test_header_only_adjustments_preserves_four_column_zero_row_landing(self):
        path=self.case/'input/repo/adjustments.csv';path.write_text('TENANT_ID,INVOICE_ID,ADJUSTMENT_CENTS,REASON\n')
        result=self.build();catalogue,bindings=self.output_json(result)
        self.assertTrue(result['verification']['catalogue_context_complete'])
        self.assertEqual(catalogue['input_evidence']['row_counts']['ADJUSTMENTS'],0)
        adjustment=next(obj for obj in catalogue['objects'] if obj['identity']['name']=='ADJUSTMENTS')
        self.assertEqual([column['path'][0] for column in adjustment['columns']],['TENANT_ID','INVOICE_ID','ADJUSTMENT_CENTS','REASON'])
        landing=next(ref for ref in bindings['references'] if ref['source_kind']=='proposed_governed_csv_landing')
        self.assertEqual(landing['source_file_sha256'],sha(path))

    def test_missing_csv_is_not_treated_as_zero_adjustments(self):
        (self.case/'input/repo/adjustments.csv').unlink()
        with self.assertRaises(FileNotFoundError): self.build()

    def test_empty_or_incomplete_csv_header_is_rejected(self):
        path=self.case/'input/repo/adjustments.csv'
        for content in ('','TENANT_ID,INVOICE_ID,ADJUSTMENT_CENTS\n'):
            with self.subTest(content=content):
                path.write_text(content)
                with self.assertRaisesRegex(ValueError,'CSV column inventory/order mismatch'): self.build()

    def test_other_empty_raw_tables_remain_explicitly_unsupported(self):
        raw=self.read('input/raw-data.json');raw['INVOICE_CDC']=[];self.write('input/raw-data.json',raw)
        with self.assertRaisesRegex(ValueError,'Empty or missing synthetic raw table: INVOICE_CDC'): self.build()

    def test_tds_mirror_drift_rejected_before_binding(self):
        path=self.case/'input/repo/billing.tds';path.write_text(path.read_text().replace('server="DMA_TABLEAU_SYNTHETIC"','server="OTHER_ACCOUNT"'))
        with self.assertRaisesRegex(ValueError,'source graph has unresolved static errors'): self.build()

    def test_forbidden_raw_relation_and_namespace_are_rejected(self):
        for replacement in ('DMA_TABLEAU.RAW.UNKNOWN_INVOICE','DMA_TABLEAU.PRIVATE.INVOICE_CDC','OTHER_DATABASE.RAW.INVOICE_CDC'):
            with self.subTest(replacement=replacement):
                self.change_sources('DMA_TABLEAU.RAW.INVOICE_CDC',replacement)
                with self.assertRaises(ValueError): self.build()
                self.change_sources(replacement,'DMA_TABLEAU.RAW.INVOICE_CDC')

    def test_source_cannot_omit_a_reviewed_raw_table(self):
        # Keep SQL parseable and namespace-approved while removing CUSTOMER_HISTORY.
        self.change_sources('DMA_TABLEAU.RAW.CUSTOMER_HISTORY','DMA_TABLEAU.RAW.INVOICE_CDC')
        with self.assertRaisesRegex(ValueError,'Tableau raw source inventory mismatch'): self.build()

    def test_truncated_catalogue_object_and_column_cannot_pass_existing_bindings(self):
        result=self.build();catalogue,bindings=self.output_json(result)
        for mutate in (lambda value:value['objects'].pop(),lambda value:value['objects'][0]['columns'].pop()):
            with self.subTest(mutation=mutate):
                changed=copy.deepcopy(catalogue);mutate(changed)
                report=self.verify_changed_output(result,changed,copy.deepcopy(bindings))
                self.assertFalse(report['catalogue_context_complete'])
                self.assertTrue(any('object' in error.lower() or 'column paths' in error for error in report['errors']))

    def test_missing_expected_binding_and_missing_export_cannot_pass(self):
        result=self.build();catalogue,bindings=self.output_json(result)
        changed=copy.deepcopy(bindings);changed['references'].pop()
        report=self.verify_changed_output(result,catalogue,changed)
        self.assertFalse(report['catalogue_context_complete'])
        self.verify_changed_output(result,catalogue,bindings)
        (self.out/'exports/columns.json').unlink()
        report=verify(Path(result['catalogue_path']),Path(result['bindings_path']))
        self.assertFalse(report['catalogue_context_complete'])

    def test_source_inventory_hash_is_required(self):
        with self.assertRaisesRegex(ValueError,'source snapshot SHA-256 required'):
            build_catalogue(self.case,self.out,'not-a-sha256')


if __name__=='__main__': unittest.main()
