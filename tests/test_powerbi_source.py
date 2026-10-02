"""Read-only Power BI source extraction and evidence-boundary regressions."""
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
from powerbi_source import inspect_repo
OPTIONAL=all(importlib.util.find_spec(name) for name in ('jsonschema','referencing','sqlglot'))
CASE=SKILL/'examples/powerbi-omni-e2e/input/repo'
MODEL='Billing.SemanticModel/model.bim'
REPORT='Billing.Report/definition/report.json'
PAGE='Billing.Report/definition/pages/ReportSectionBilling/page.json'
VISUAL='Billing.Report/definition/pages/ReportSectionBilling/visuals/RevenueTrend/visual.json'

@unittest.skipUnless(OPTIONAL,'Optional Power BI source schema/SQL dependencies are required')
class PowerBISourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.repo=Path(self.tmp.name)/'repo';shutil.copytree(CASE,self.repo)
    def read(self,path):return json.loads((self.repo/path).read_text())
    def write(self,path,value):
        p=self.repo/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(value,indent=2)+'\n')
    def mutate(self,path,change):
        value=self.read(path);change(value);self.write(path,value)
    def assert_error(self,fragment=None):
        graph=inspect_repo(self.repo);self.assertFalse(graph['static_coverage_complete']);self.assertGreater(graph['counts']['errors'],0)
        if fragment:self.assertIn(fragment,' '.join(g['message'] for g in graph['gaps']))
        return graph
    def test_complete_native_inventory_and_official_schema_scope(self):
        r=inspect_repo(self.repo)
        self.assertEqual(r['counts'],{'assets':12,'projects':1,'tables':3,'columns':20,'measures':9,'partitions':3,'relationships':1,'roles':2,'pages':1,'visuals':3,'filters':5,'edges':48,'errors':0,'review_gaps':2,'schema_validated_files':10})
        self.assertTrue(r['static_coverage_complete']);self.assertFalse(r['native_runtime_validated'])
        self.assertTrue(all(v['valid'] for v in r['schema_validation']))
        self.assertEqual(r['model'],self.read(MODEL))
        self.assertTrue(all(m['table']=='Scenario' for m in r['measures']))
        self.assertEqual({g['kind'] for g in r['gaps']},{'native_runtime_unverified','bounded_semantics'})
    def test_m_dax_column_mappings_and_source_identity_preserved(self):
        r=inspect_repo(self.repo);invoice=next(p for p in r['partitions'] if p['table']=='Invoices')
        self.assertEqual(invoice['expression'],r['model']['model']['tables'][0]['partitions'][0]['source']['expression'])
        self.assertIn('Table.AddColumn',invoice['expression']);self.assertIn('Date.StartOfMonth',invoice['expression'])
        self.assertEqual(invoice['connection']['platform_instance'],'DMA_POWERBI_SYNTHETIC')
        self.assertEqual(invoice['connection']['catalog'],'DMA_POWERBI')
        self.assertEqual(set(invoice['sql_analysis']['physical_refs']),{'DMA_POWERBI.RAW.'+name for name in ('INVOICE_CDC','PAYMENT_CDC','CUSTOMER_HISTORY','ADJUSTMENTS')})
        self.assertEqual(len(invoice['sql_analysis']['ctes']),5)
        outstanding=next(c for c in r['columns'] if c['table']=='Invoices' and c['name']=='Outstanding Cents')
        self.assertEqual(outstanding['expression'],'Invoices[Net Cents] - Invoices[Paid Cents]')
        net=next(c for c in r['columns'] if c['table']=='Invoices' and c['name']=='Net Cents')
        self.assertEqual(net['source_column'],'NET_CENTS')
        self.assertIn('KEEPFILTERS',next(m['expression'] for m in r['measures'] if m['name']=='Posted Intersection Cents'))
    def test_defaults_and_ordered_projection_provenance(self):
        r=inspect_repo(self.repo)
        self.assertEqual(r['report_defaults'],{'start_date':'2026-01-01','end_date':'2026-03-01','status':'posted','segment':'ALL','multipliers':[1]})
        self.assertNotIn('tenant',r['report_defaults']);self.assertIn('external harness',r['security_context_basis'])
        self.assertEqual([(f['id'],f['operator']) for f in r['filters']],[('ReportingStart','gte'),('ReportingEnd','lt'),('StatusSelection','in'),('SegmentSelection','all'),('MultiplierSelection','in')])
        self.assertEqual([v['title'] for v in r['visuals']],['Revenue Trend','Segment Share','KPI Totals'])
        self.assertEqual([(p['table'],p['property']) for p in r['visuals'][0]['projections'][:2]],[('Invoices','Invoice Month'),('Customers','Segment')])
        self.assertTrue(all(p['kind']=='measure' for p in r['visuals'][2]['projections']))
        self.assertTrue(all(f['path']==REPORT and f['scope']=='report' for f in r['filters']))
        self.assertEqual(r['report_default_evidence']['start_date']['filter_id'],'ReportingStart')
    def test_relationship_and_two_table_role_filters_are_preserved(self):
        r=inspect_repo(self.repo);relation=r['relationships'][0]
        self.assertEqual((relation['fromTable'],relation['fromColumn'],relation['toTable'],relation['toColumn']),('Invoices','Customer History Key','Customers','Customer History Key'))
        self.assertEqual(relation['crossFilteringBehavior'],'oneDirection')
        for role in r['roles']:
            tenant=role['name'][-1]
            self.assertEqual({p['name']:p['filterExpression'] for p in role['tablePermissions']},{t:t+'[Tenant ID] = "'+tenant+'"' for t in ('Invoices','Customers')})
    def test_current_bytes_hash_and_snapshot_are_recomputed(self):
        before=inspect_repo(self.repo);p=self.repo/MODEL;p.write_bytes(p.read_bytes()+b'\n')
        after=inspect_repo(self.repo);self.assertTrue(after['static_coverage_complete'])
        self.assertNotEqual(before['source_snapshot_sha256'],after['source_snapshot_sha256'])
        for asset in after['assets']:self.assertEqual(asset['sha256'],hashlib.sha256((self.repo/asset['path']).read_bytes()).hexdigest())
    def test_relative_model_reference_can_resolve_inside_repo(self):
        self.assertTrue(inspect_repo(self.repo)['static_coverage_complete'])
        self.assertEqual(inspect_repo(self.repo)['projects'][0]['dataset_reference'],{'byPath':{'path':'../Billing.SemanticModel'}})
    def test_path_escape_absolute_windows_and_remote_model_fail(self):
        original=self.read('Billing.Report/definition.pbir')
        for path in ('../../outside','/private/tmp','..\\Billing.SemanticModel','https://example.invalid/model'):
            with self.subTest(path=path):
                changed=copy.deepcopy(original);changed['datasetReference']={'byPath':{'path':path}};self.write('Billing.Report/definition.pbir',changed);self.assert_error()
        changed=copy.deepcopy(original);changed['datasetReference']={'byConnection':{'connectionString':'Data Source=remote'}};self.write('Billing.Report/definition.pbir',changed);self.assert_error('Remote/ambiguous')
    def test_file_and_directory_symlinks_are_not_followed(self):
        outside=Path(self.tmp.name)/'external.bim';outside.write_text('{}')
        p=self.repo/MODEL;p.unlink();p.symlink_to(outside);self.assert_error('unsupported')
        p.unlink();shutil.copyfile(CASE/MODEL,p)
        (self.repo/'alias').symlink_to(self.repo/'Billing.SemanticModel',target_is_directory=True);self.assert_error('symlink')
    def test_missing_linked_model_is_not_inferred(self):
        (self.repo/MODEL).unlink();self.assert_error('Missing/invalid native JSON artifact')
    def test_unsupported_pbix_tmdl_and_pending_changes_are_visible(self):
        for relative,content in [('unavailable.pbix',b'opaque'),('Billing.SemanticModel/definition/tables.tmdl',b'table Other'),('Billing.SemanticModel/.pbi/unappliedChanges.json',b'{}')]:
            with self.subTest(relative=relative):
                p=self.repo/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(content);r=self.assert_error()
                self.assertIn(relative,{a['path'] for a in r['assets']});p.unlink()
    def test_unbound_report_json_not_silently_ignored(self):
        self.write('other-report.json',self.read(REPORT));self.assert_error('Unreferenced model/report/JSON asset')
    def test_duplicate_json_keys_fail(self):
        (self.repo/'Billing.pbip').write_text('{"version":"1.0","version":"2.0"}')
        self.assert_error('Duplicate JSON key')
    def test_unknown_schema_cannot_trigger_network_resolution(self):
        self.mutate(REPORT,lambda x:x.update({'$schema':'https://example.invalid/schema.json'}));self.assert_error('not in pinned Microsoft bundle')
    def test_schema_illtyped_value_is_a_gap_not_parser_crash(self):
        self.mutate(REPORT,lambda x:x.update({'$schema':{}}));self.assert_error()
    def test_official_schema_rejects_malformed_visual_position(self):
        self.mutate(VISUAL,lambda x:x['position'].update(width='wide'));self.assert_error('not of type')
    def test_duplicate_table_and_lineage_tags(self):
        original=self.read(MODEL)
        self.mutate(MODEL,lambda x:x['model']['tables'].append(copy.deepcopy(x['model']['tables'][0])));self.assert_error('Duplicate/missing table')
        self.write(MODEL,original)
        self.mutate(MODEL,lambda x:x['model']['tables'][0]['columns'][1].update(lineageTag=x['model']['tables'][0]['columns'][0]['lineageTag']));self.assert_error('Duplicate native lineageTag')
    def test_duplicate_measure_names_and_same_table_collisions(self):
        original=self.read(MODEL)
        self.mutate(MODEL,lambda x:x['model']['tables'][0].update(measures=[copy.deepcopy(x['model']['tables'][2]['measures'][0])]));self.assert_error('Duplicate')
        self.write(MODEL,original)
        def collide(x):
            measure=x['model']['tables'][2]['measures'].pop(1);x['model']['tables'][0]['measures']=[measure]
        self.mutate(MODEL,collide);self.assert_error('column/measure identity collision')
    def test_missing_source_column_mapping(self):
        self.mutate(MODEL,lambda x:x['model']['tables'][0]['columns'][0].pop('sourceColumn'));self.assert_error('Source column mapping is missing')
    def test_unresolved_dax_reference(self):
        self.mutate(MODEL,lambda x:x['model']['tables'][2]['measures'][0].update(expression='SUM(Invoices[Missing Column])'));self.assert_error('Unresolved native field reference')
    def test_unsupported_dax_is_retained_for_runtime_instead_of_executed(self):
        self.mutate(MODEL,lambda x:x['model']['tables'][2]['measures'][0].update(expression='AVERAGEX(Invoices,Invoices[Net Cents])'))
        r=inspect_repo(self.repo);self.assertIn('AVERAGEX',r['measures'][0]['expression']);self.assertFalse(r['native_runtime_validated'])
        self.assertIn('bounded_semantics',{g['kind'] for g in r['gaps']})
    def test_dynamic_m_connection_and_directquery_are_gaps(self):
        original=self.read(MODEL)
        def dynamic(x):
            source=x['model']['tables'][0]['partitions'][0]['source'];source['expression']=source['expression'].replace('"DMA_POWERBI_SYNTHETIC"','ServerParameter')
        self.mutate(MODEL,dynamic);self.assert_error('Dynamic/unbound')
        self.write(MODEL,original);self.mutate(MODEL,lambda x:x['model']['tables'][0]['partitions'][0].update(mode='directQuery'));self.assert_error('Only Import M')
    def test_inactive_many_to_many_and_bidirectional_relationships_fail(self):
        original=self.read(MODEL)
        for field,value in [('isActive',False),('toCardinality','many'),('crossFilteringBehavior','bothDirections'),('securityFilteringBehavior','bothDirections')]:
            with self.subTest(field=field):
                changed=copy.deepcopy(original);changed['model']['relationships'][0][field]=value;self.write(MODEL,changed);self.assert_error('active many-to-one')
    def test_missing_and_unresolved_relationships_fail(self):
        original=self.read(MODEL);self.mutate(MODEL,lambda x:x['model'].update(relationships=[]));self.assert_error('one unambiguous')
        self.write(MODEL,original);self.mutate(MODEL,lambda x:x['model']['relationships'][0].update(toColumn='Missing Key'));self.assert_error('Unresolved native field')
    def test_duplicate_roles_and_unresolved_security_column(self):
        original=self.read(MODEL);self.mutate(MODEL,lambda x:x['model']['roles'].append(copy.deepcopy(x['model']['roles'][0])));self.assert_error('Duplicate/missing role')
        self.write(MODEL,original);self.mutate(MODEL,lambda x:x['model']['roles'][0]['tablePermissions'][0].update(filterExpression='Invoices[Missing Tenant] = "A"'));self.assert_error('Unresolved native field')
    def test_stale_projection_queryref_and_native_field_fail(self):
        original=self.read(VISUAL)
        self.mutate(VISUAL,lambda x:x['visual']['query']['queryState']['Values']['projections'][0].update(queryRef='Invoices.Other'));self.assert_error('Stale visual queryRef')
        self.write(VISUAL,original);self.mutate(VISUAL,lambda x:x['visual']['query']['queryState']['Values']['projections'][0]['field']['Column'].update(Property='Other'));self.assert_error('Unresolved native field')
    def test_duplicate_visual_identity_and_duplicate_projection(self):
        original=self.read(VISUAL);self.mutate(VISUAL,lambda x:x.update(name='KPITotals'));self.assert_error('visual identity')
        self.write(VISUAL,original);self.mutate(VISUAL,lambda x:x['visual']['query']['queryState']['Values']['projections'].append(copy.deepcopy(x['visual']['query']['queryState']['Values']['projections'][0])));self.assert_error('Duplicate visual queryRef')
    def test_visual_hidden_field_and_densification_are_gaps(self):
        original=self.read(VISUAL)
        self.mutate(VISUAL,lambda x:x['visual']['query']['queryState']['Values'].update(showAll=True));self.assert_error('show-items-with-no-data')
        self.write(VISUAL,original);self.mutate(VISUAL,lambda x:x['visual']['query']['queryState']['Values']['projections'][0].update(hidden=True));self.assert_error('Hidden/inactive')
    def test_filter_field_and_predicate_provenance_must_agree(self):
        def change(x):x['filterConfig']['filters'][0]['filter']['Where'][0]['Condition']['Comparison']['Left']['Column']['Property']='Invoice Month'
        self.mutate(REPORT,change);self.assert_error('Filter field and predicate provenance mismatch')
    def test_page_and_visual_filters_are_preserved_but_fail_qualified_subset(self):
        for path in (PAGE,VISUAL):
            with self.subTest(path=path):
                f=copy.deepcopy(self.read(REPORT)['filterConfig']['filters'][2]);f['name']='ExtraFilter'
                self.mutate(path,lambda x:x.update(filterConfig={'filters':[f]}));r=self.assert_error('Page/visual filters')
                self.assertIn('ExtraFilter',{f['id'] for f in r['filters']})
                self.mutate(path,lambda x:x.pop('filterConfig'))
    def test_missing_default_and_duplicate_filters_fail(self):
        original=self.read(REPORT);self.mutate(REPORT,lambda x:x['filterConfig']['filters'].pop());self.assert_error('default coverage is incomplete')
        self.write(REPORT,original);self.mutate(REPORT,lambda x:x['filterConfig']['filters'].append(copy.deepcopy(x['filterConfig']['filters'][0])));self.assert_error('Duplicate report filter identity')
    def test_page_interactions_and_bookmarks_are_not_silently_dropped(self):
        self.mutate(PAGE,lambda x:x.update(visualInteractions=[]));self.assert_error('interactions')
        self.write('Billing.Report/definition/bookmarks/bookmarks.json',{});self.assert_error('schema')
    def test_malformed_model_structure_is_a_gap(self):
        self.mutate(MODEL,lambda x:x.update(model=[]));self.assert_error()

if __name__=='__main__':unittest.main()
