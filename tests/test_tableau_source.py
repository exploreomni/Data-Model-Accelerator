"""Static Tableau coverage and bounded package-read regressions."""
from pathlib import Path
import copy
import importlib.util
import json
import shutil
import stat
import sys
import tempfile
import unittest
import warnings
import xml.etree.ElementTree as E
import zipfile

SKILL=Path(__file__).resolve().parents[1]/'skills/data-model-accelerator'
sys.path.insert(0,str(SKILL/'scripts'))
from tableau_source import inspect_repo,inspect_package,validate_official_schema,_xml,CredentialContentError
CASE=SKILL/'examples/tableau-omni-e2e'
HAS_SQL=importlib.util.find_spec('sqlglot') is not None

class TableauCredentialBoundaryTests(unittest.TestCase):
    CANARY='DMA_SYNTHETIC_CREDENTIAL_CANARY'

    def test_credential_attributes_are_rejected_without_values(self):
        for key in ('password','PaSsWoRd','access-token','CLIENT_SECRET','private-key','pwd','authorization'):
            with self.subTest(key=key):
                with self.assertRaises(CredentialContentError) as error:
                    _xml(('<workbook><connection '+key+'="'+self.CANARY+'"/></workbook>').encode())
                self.assertNotIn(self.CANARY,str(error.exception))

    def test_nested_elements_and_property_fields_are_rejected(self):
        for xml in ('<password>{}</password>','<Password value="{}"/>',
                    '<property name="password" value="{}"/>',
                    '<connection-property key="access_token">{}</connection-property>',
                    '<entry name="client-secret"><value>{}</value></entry>'):
            with self.subTest(xml=xml):
                with self.assertRaises(CredentialContentError):
                    _xml(('<workbook><connection>'+xml.format(self.CANARY)+'</connection></workbook>').encode())

    def test_empty_credentials_and_safe_connection_lineage_are_preserved(self):
        root=_xml(b'<workbook><connection password="" username="demo" server="synthetic" dbname="RAW" schema="PUBLIC"><property name="password" value=""/></connection></workbook>')
        self.assertEqual(root.find('connection').get('server'),'synthetic')
        self.assertEqual(root.find('connection').get('schema'),'PUBLIC')

    def test_inventory_rejects_twb_and_tds_before_schema_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for suffix,tag in (('twb','workbook'),('tds','datasource')):
                (root/('source.'+suffix)).write_text('<'+tag+'><connection password="'+self.CANARY+'"/></'+tag+'>')
            graph=inspect_repo(root)
            self.assertEqual(len([g for g in graph['gaps'] if g['kind']=='credential_content']),2)
            self.assertEqual(len(graph['assets']),2)
            self.assertTrue(all(a['sha256'] for a in graph['assets']))
            self.assertFalse(graph['static_coverage_complete'])
            self.assertNotIn(self.CANARY,json.dumps(graph))

    def test_archive_and_official_schema_paths_do_not_echo_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source.twb'
            source.write_text('<workbook><connection password="'+self.CANARY+'"/></workbook>')
            with self.assertRaises(CredentialContentError) as error:validate_official_schema(source)
            self.assertNotIn(self.CANARY,str(error.exception))
            package=root/'source.twbx'
            with zipfile.ZipFile(package,'w') as archive:archive.write(source,'source.twb')
            result=inspect_package(package)
            self.assertFalse(result['safe'])
            self.assertNotIn(self.CANARY,json.dumps(result))


@unittest.skipUnless(HAS_SQL,'Optional SQLGlot is required for custom SQL analysis')
class TableauSourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.repo=Path(self.tmp.name)/'repo';shutil.copytree(CASE/'input/repo',self.repo)
        self.package=Path(self.tmp.name)/'test.twbx'
    def mutate(self,path,fn):
        p=self.repo/path;tree=E.parse(p);fn(tree.getroot());tree.write(p,encoding='utf-8',xml_declaration=True)
    def kinds(self):return {g['kind'] for g in inspect_repo(self.repo)['gaps'] if g['severity']=='error'}
    def makezip(self,entries,compress=zipfile.ZIP_DEFLATED):
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            with zipfile.ZipFile(self.package,'w',compression=compress) as z:
                for name,data in entries:z.writestr(name,data)
        return inspect_package(self.package)
    def test_exact_source_coverage_and_mirror_authority(self):
        r=inspect_repo(self.repo)
        self.assertEqual((r['counts']['workbooks'],r['counts']['datasources'],r['counts']['worksheets'],r['counts']['dashboards']),(1,1,3,1))
        self.assertEqual((r['counts']['fields'],r['counts']['calculations'],r['counts']['parameters']),(29,15,5))
        self.assertEqual(r['counts']['errors'],0);self.assertTrue(r['static_coverage_complete']);self.assertFalse(r['native_runtime_validated'])
        self.assertEqual(r['mirrors'][0]['authority'],'consistency_mirror_only')
        self.assertTrue(r['mirrors'][0]['matches_embedded'])
        self.assertEqual(len(r['datasources'][0]['sql_analysis']['physical_refs']),4)
    def test_native_context_table_scope_and_defaults_preserved(self):
        r=inspect_repo(self.repo)
        for sheet in r['worksheets']:
            self.assertEqual([(f['caption'],f['stage'],f['member']) for f in sheet['filters']],[('Date Window','context',True),('Segment Selection','dimension',True)])
            self.assertEqual([f['caption'] for f in sheet['datasource_filters']],['Posted Population','Tenant Population'])
        share=next(s for s in r['worksheets'] if s['name']=='Revenue Share')['table_calculations'][0]
        self.assertEqual(share['addressing'],['[Segment]']);self.assertEqual(share['partitioning'],['[Invoice Month]'])
        self.assertIn('Remaining selected view dimensions',share['partition_basis'])
        self.assertEqual({p['caption']:p['default'] for p in r['parameters']},{'Tenant':'A','Start Date':'2026-01-01','End Date':'2026-03-01','Segment':'ALL','Multiplier':1.0})
    def test_package_matches_repository_without_extraction(self):
        r=inspect_package(CASE/'input/packages/billing.twbx',self.repo)
        self.assertTrue(r['safe']);self.assertTrue(r['matches_repo']);self.assertFalse(r['extracted']);self.assertEqual(len(r['members']),3)
    def test_tds_sql_drift(self):
        self.mutate('billing.tds',lambda t:setattr(t.find('./connection/relation'),'text','SELECT 1 AS AMOUNT_CENTS'))
        self.assertIn('tds_mirror_drift',self.kinds())
    def test_raw_mapping_duplicate(self):
        def change(t):
            records=t.find('./datasources/datasource[@name="federated.billing"]/connection/metadata-records')
            records.append(copy.deepcopy(records[0]))
        self.mutate('billing.twb',change);self.assertIn('ambiguous_raw_mapping',self.kinds())
    def test_missing_calculation_reference(self):
        self.mutate('billing.twb',lambda t:t.find('./datasources/datasource[@name="federated.billing"]/column[@name="[Net Cents]"]/calculation').set('formula','[Missing Amount]'))
        self.assertIn('unresolved_calculation',self.kinds())
    def test_missing_table_calculation_scope(self):
        def change(t):
            ci=t.find('./worksheets/worksheet[@name="Revenue Share"]/table/view/datasource-dependencies/column-instance[@column="[Revenue Share]"]')
            ci.remove(ci.find('table-calc'))
        self.mutate('billing.twb',change);self.assertIn('missing_table_calculation_scope',self.kinds())
    def test_unknown_table_addressing(self):
        self.mutate('billing.twb',lambda t:t.find('./worksheets/worksheet[@name="Revenue Share"]/table/view/datasource-dependencies/column-instance/table-calc/order').set('field','[federated.billing].[Customer ID]'))
        self.assertIn('unresolved_table_calculation',self.kinds())
    def test_omitted_sheet_detected_by_dashboard(self):
        def change(t):
            sheets=t.find('worksheets');sheets.remove(sheets[0])
        self.mutate('billing.twb',change);self.assertIn('unresolved_dashboard_sheet',self.kinds())
    def test_duplicate_workbook_identity(self):
        shutil.copyfile(self.repo/'billing.twb',self.repo/'duplicate.twb')
        self.assertIn('duplicate_workbook_identity',self.kinds())
    def test_duplicate_field(self):
        def change(t):
            ds=t.find('./datasources/datasource[@name="federated.billing"]');ds.append(copy.deepcopy(ds.find('column')))
        self.mutate('billing.twb',change);self.assertIn('duplicate_or_missing_field',self.kinds())
    def test_published_datasource_is_gap(self):
        self.mutate('billing.twb',lambda t:E.SubElement(t.find('./datasources/datasource[@name="federated.billing"]'),'repository-location',{'path':'/datasources','id':'external'}))
        self.assertIn('unresolved_native_dependency',self.kinds())
    def test_unbound_tds_not_promoted(self):
        (self.repo/'billing.twb').unlink();self.assertTrue({'unbound_tds','no_workbooks'}<=self.kinds())
    def test_unsupported_filter_not_silently_coerced(self):
        self.mutate('billing.twb',lambda t:t.find('./worksheets/worksheet/table/view/filter/groupfilter').set('function','union'))
        self.assertIn('unsupported_filter',self.kinds())
    def test_invalid_native_context_not_treated_as_dimension(self):
        self.mutate('billing.twb',lambda t:t.find('./worksheets/worksheet/table/view/filter').set('context','maybe'))
        self.assertIn('invalid_context_flag',self.kinds())
    def test_filter_member_level_must_match_column(self):
        self.mutate('billing.twb',lambda t:t.find('./worksheets/worksheet/table/view/filter/groupfilter').set('level','[none:Segment Selection:nk]'))
        self.assertIn('filter_level_mismatch',self.kinds())
    def test_dtd_and_entities_rejected(self):
        (self.repo/'billing.twb').write_text('<!DOCTYPE workbook [<!ENTITY x "hello">]><workbook>&x;</workbook>')
        self.assertIn('xml_invalid',self.kinds())
    def test_utf16_xml_rejected(self):
        with self.assertRaisesRegex(ValueError,'UTF-8'):_xml('<workbook/>'.encode('utf-16'))
    def test_archive_traversal(self):
        r=self.makezip([('../escape.twb',b'<workbook/>')]);self.assertFalse(r['safe']);self.assertIn('Unsafe',r['errors'][0])
    def test_archive_windows_path(self):
        r=self.makezip([('C:\\escape.twb',b'<workbook/>')]);self.assertFalse(r['safe'])
    def test_archive_duplicate(self):
        r=self.makezip([('a.twb',b'<workbook/>'),('a.twb',b'<workbook/>')]);self.assertFalse(r['safe']);self.assertIn('Duplicate',r['errors'][0])
    def test_archive_case_collision(self):
        r=self.makezip([('a.twb',b'<workbook/>'),('A.twb',b'<workbook/>')]);self.assertFalse(r['safe'])
    def test_archive_symlink(self):
        info=zipfile.ZipInfo('a.twb');info.external_attr=(stat.S_IFLNK|0o777)<<16
        r=self.makezip([(info,b'/etc/passwd')]);self.assertFalse(r['safe']);self.assertIn('Symlink',r['errors'][0])
    def test_archive_bomb_ratio(self):
        r=self.makezip([('a.twb',b' ' * 200000)]);self.assertFalse(r['safe']);self.assertIn('high-ratio',r['errors'][0])
    def test_archive_member_count(self):
        r=self.makezip([(f'{i}.csv',b'1') for i in range(51)]);self.assertFalse(r['safe']);self.assertIn('Too many',r['errors'][0])
    def test_archive_oversized_member(self):
        r=self.makezip([('a.twb',b' ' * 2000001)],zipfile.ZIP_STORED);self.assertFalse(r['safe'])
    def test_archive_repo_drift(self):
        self.makezip([('billing.twb',b'<workbook/>')]);r=inspect_package(self.package,self.repo)
        self.assertFalse(r['safe']);self.assertIn('differs',r['errors'][0])
    def test_official_schema_dependency_gap_is_not_validation(self):
        r=validate_official_schema(self.repo/'billing.twb')
        self.assertFalse(r['validated']);self.assertTrue(r['status'].startswith('unavailable'))
        self.assertFalse(r['native_application_opened'])

if __name__=='__main__':unittest.main()
