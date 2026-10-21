"""Scoped legacy comparison review and portable exports; DOM tests do not prove print geometry."""
import copy
import csv
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import zipfile

import test_portal_navigation as navigation
import test_engagement_stages as stages_fixture
import test_legacy_alignment_workflow as alignment_fixture
import legacy_alignment as alignment

portal = navigation.portal


def summary():
    def counts(total=0, mapped=0, unmatched=0):
        return dict(total=total, mapped=mapped, unmatched=unmatched, unsupported=0, excluded=0)
    def source(table):
        return dict(table_id=table, table_name='Existing ' + table, kind='table', label=table)
    def row(identity, sources, targets, relationship='direct', behavior='preserve', review='accepted'):
        return dict(id=identity, legacy_sources=[source(s) for s in sources],
            targets=[dict(model_id=t, kind='table') for t in targets], model_ids=targets,
            relationship=relationship, disposition=relationship if relationship in ('split', 'merge') else 'preserve',
            status='mapped', behavior=behavior, basis='structural_binding', rationale='Supplied ' + identity,
            review_status=review, evidence_labels=['schema'])
    return dict(schema_version=1, status='recorded', qualification='Supplied evidence; parity and acceptance unverified.', domains=[
        dict(domain_id='orders', mode='refactor', comparison_requested=True, behavior='preserve',
             baseline_status='partial', alignment_status='recorded', freshness='current',
             model_ids=['silver.orders', 'gold.orders'], comparison_sha256='a'*64, omitted_details=False,
             coverage=dict(tables=counts(3, 2, 1), columns=counts(), rules=counts()),
             tables=[dict(id=t, name='Existing '+t, model_ids=[], completeness=dict(columns='unknown', rules='unknown'), coverage={}) for t in ('a', 'b', 'gap')],
             mappings=[row('split', ['a'], ['silver.orders','gold.orders'], 'split'),
                       row('merge', ['a','b'], ['gold.orders'], 'merge', 'correct'),
                       row('pending', ['b'], ['silver.orders'], review='proposed')],
             unmatched=[source('gap')]),
        dict(domain_id='staging', mode='new_model', comparison_requested=True, behavior='undecided',
             baseline_status='not_supplied', alignment_status='unassessed', freshness='current',
             model_ids=['bronze.orders'], coverage={}, tables=[], mappings=[], unmatched=[], omitted_details=False)])


class AlignmentProjectionTests(unittest.TestCase):
    def test_allowlist_safe_text_csv_and_complete_markdown(self):
        raw = summary(); raw['source_path'] = 'PRIVATE_SOURCE_PATH'
        raw['domains'][0]['mappings'][0].update(sql='PRIVATE_QUERY', row_values=['PRIVATE_VALUE'])
        raw['domains'][0]['mappings'][0]['rationale'] = '=CMD <script>alert(1)</script>'
        data = portal._legacy_alignment_presentation(raw)
        self.assertNotIn('PRIVATE_', json.dumps(data))
        self.assertEqual(len(data['rows']), 4)
        rows = list(csv.DictReader(io.StringIO(data['summary_csv'])))
        self.assertEqual(len(rows), 4)
        self.assertTrue(rows[0]['rationale'].startswith("'=CMD"))
        self.assertIn('&lt;script&gt;', data['summary_markdown'])
        self.assertIn('Target model to existing tables', data['summary_markdown'])
        self.assertIn('Baseline: not', data['summary_markdown'])
        self.assertIn('split', data['summary_markdown'])

    def test_actual_module_full_subset_and_missing_baseline(self):
        h = stages_fixture.StageTests('test_design_only_and_forged_approval_never_unlock_code')
        h.setUp(); self.addCleanup(h.doCleanups)
        doc = copy.deepcopy(h.doc); doc['revision'] = 2; doc['entities'][2]['domain'] = 'private'
        h.action('import-design', document=doc)
        alignment.configure(h.state, alignment_fixture.config())
        alignment.configure(h.state, dict(alignment_fixture.config(), domain_id='private'))
        missing = portal._presentation(h.state)['legacy_alignment']
        self.assertEqual(missing['domains'][0]['baseline_status'], 'not_supplied')
        baseline = alignment_fixture.baseline()
        shared = copy.deepcopy(baseline['tables'][0]); shared.update(id='private.shared', native_id='shared', label='PRIVATE_SHARED_TABLE', consumer_domains=['commerce','private'])
        private = copy.deepcopy(baseline['tables'][0]); private.update(id='private.table', native_id='private', label='PRIVATE_TABLE', consumer_domains=['private'])
        second = copy.deepcopy(baseline['tables'][0]); second.update(id='legacy.other', native_id='other', label='Old other')
        baseline['tables'].extend([shared,private,second])
        alignment.register_baseline(h.state, baseline, h.run)
        mapping = alignment_fixture.mappings()
        mapping['mappings'][0].update(sources=[dict(table_id='legacy.orders',kind='table')], targets=[dict(model_id='orders',kind='table'),dict(model_id='customers',kind='table')])
        merge = copy.deepcopy(mapping['mappings'][0]); merge.update(id='merged',sources=[dict(table_id='legacy.orders',kind='table'),dict(table_id='legacy.other',kind='table')],targets=[dict(model_id='orders',kind='table')])
        mapping['mappings'].append(merge)
        alignment.register_alignment(h.state, mapping, h.run)
        full = portal._presentation(h.state)['legacy_alignment']
        self.assertIn('PRIVATE_SHARED_TABLE', json.dumps(full))
        projected = portal._legacy_alignment_presentation(alignment.public_summary(h.state, {'orders','customers'}))
        self.assertNotIn('PRIVATE_', json.dumps(projected))
        self.assertEqual([d['domain_id'] for d in projected['domains']], ['commerce'])
        self.assertEqual({r['relationship'] for r in projected['domains'][0]['mappings']}, {'split','merge'})
        self.assertFalse(portal._legacy_alignment_presentation(alignment.public_summary(h.state, set()))['domains'])
        self.assertNotIn('legacy_alignment', portal._presentation(h.state, audience='audit'))
        # An explicit review invokes the module with the declared model inventory.
        review = dict(schema_version=1, title='Scoped synthetic review',
            source_fingerprint=portal.source_fingerprint(h.state), context_sha256=portal.context_fingerprint(h.state),
            design_binding={k:h.state['workflow']['design'][k] for k in ('id','revision','sha256')},
            target={k:h.state['answers'][k] for k in ('framework','warehouse')},
            models=[dict(id='customers',name='Customers',layer='gold'),dict(id='orders',name='Orders',layer='gold')],
            relationships=[], artifacts=[])
        actual = portal._presentation(h.state, review)['legacy_alignment']
        self.assertNotIn('PRIVATE_', json.dumps(actual))
        h.state['workflow']['design']['entities'][1]['grain'] = 'Changed grain'
        stale = portal._legacy_alignment_presentation(alignment.public_summary(h.state))
        self.assertEqual(stale['domains'][0]['freshness'], 'stale')

    def test_actual_module_explicit_exclusion_and_new_target_survive_scoped_projection(self):
        h=stages_fixture.StageTests('test_design_only_and_forged_approval_never_unlock_code')
        h.setUp();self.addCleanup(h.doCleanups)
        alignment.configure(h.state,alignment_fixture.config())
        alignment.register_baseline(h.state,alignment_fixture.baseline(),h.run)
        mapping=alignment_fixture.mappings();row=mapping['mappings'][0]
        row.update(id='retirement',sources=[dict(table_id='legacy.orders',kind='table')],targets=[],
                   disposition='retire_candidate',status='unmatched',basis='reviewed_definition')
        new=copy.deepcopy(row);new.update(id='new-target',sources=[],targets=[dict(model_id='products',kind='table')],disposition='new',status='mapped')
        mapping['mappings'].append(new)
        alignment.register_alignment(h.state,mapping,h.run)
        raw=alignment.public_summary(h.state)
        alignment.record_decisions(h.state,dict(schema_version=1,kind='human_legacy_alignment_review',
            engagement_id=h.state['engagement_id'],domain_id='commerce',comparison_sha256=raw['domains'][0]['comparison_sha256'],
            reviewer='Synthetic reviewer',review_reference='synthetic://human-review',
            decisions=[dict(mapping_id='retirement',decision='accepted',rationale='Explicit reviewed retirement candidate.')]))
        projected=portal._legacy_alignment_presentation(alignment.public_summary(h.state,{'orders','customers','products'}))
        mapped={row['id']:row for row in projected['rows']}
        self.assertEqual(mapped['retirement']['review_status'],'accepted')
        self.assertEqual(mapped['new-target']['disposition'],'new')
        self.assertEqual(projected['domains'][0]['coverage']['tables']['excluded'],1)
        self.assertIn('retire',projected['summary_markdown'])


@unittest.skipUnless(shutil.which('node'), 'Node required for offline control tests')
class AlignmentDomTests(unittest.TestCase):
    def page(self, data, assertions, prefix='', second_boot=False):
        data['generated_deliverables'] = portal.generated_deliverables(data)
        navigation.PortalNavigationTests.page(self, data, assertions, prefix, second_boot)

    payload = navigation.PortalNavigationTests.payload

    def data(self):
        data = self.payload(); data['legacy_alignment'] = portal._legacy_alignment_presentation(summary())
        data['review']['assets'] = [dict(id='report',name='Order report')]
        data['review']['models'][2].update(asset_ids=['report'], artifact_id='1')
        data['review']['decisions'] = [dict(id='d1',question='Review order grain?',model_ids=['gold.orders'],status='pending')]
        data['generated_deliverables'] = portal.generated_deliverables(data)
        return data

    def test_first_click_filters_counts_both_directions_and_genuine_links(self):
        css=(portal.ASSETS/'portal.css').read_text()
        self.assertIn('.review-section .alignment-filters>div{min-width:180px;flex:1 1 180px}',css)
        self.assertIn('.review-section .alignment-filters label.check{flex:1 1 220px;',css)
        self.page(self.data(), r"""
assert.equal(el('replacement-title').textContent,'Compare with existing tables');
assert.equal(el('replacement-table').hidden,true);assert.equal(el('alignment-screen').hidden,false);
assert.equal(alignmentCoverageLine('tables',{total:3,mapped:2,unmatched:1,unsupported:0,excluded:0}),'Tables: 2 of 3 mapped; 1 unmatched');
assert.equal(alignmentCoverageLine('columns',{total:0,mapped:0,unmatched:0,unsupported:0}),'Columns: No items supplied');
assert.equal(alignmentCoverageLine('rules',undefined),'Rules: Not assessed');
assert.equal(alignmentCoverageLine('rules',{total:4}),'Rules: Not assessed');
assert.equal(alignmentCoverageLine('tables',{total:3,mapped:0,unmatched:0,unsupported:1,excluded:2}),'Tables: 0 of 3 mapped; 1 unsupported; 2 explicitly excluded');
assert.equal(el('alignment-coverage').querySelector('.alignment-coverage-lines').children.length,3);
assert.equal(alignmentLabel('structural_binding'),'Structural binding');assert.equal(alignmentLabel('not_supplied'),'Not supplied');
assert(legacyAlignment.summary_csv.includes('structural_binding'));
location.hash='#replacement-map';listeners.hashchange[0]();assert.equal(el('delivery').hidden,false);assert.equal(el('replacement-map').focused,true);
const rows=legacyAlignment.rows,ids=filters=>rows.filter(row=>alignmentMatches(row,filters)).map(row=>row.id);
assert.deepEqual(ids({changed:true}),['split','merge']);assert.deepEqual(ids({unresolved:true}),['pending','unmatched:1']);
assert.deepEqual(ids({table:JSON.stringify(['orders','a'])}),['split','merge']);
assert.deepEqual(ids({model:'silver.orders'}),['split','pending']);assert.deepEqual(ids({asset:'report'}),['split','merge']);
assert.deepEqual(ids({domain:'staging'}),[]);assert.deepEqual(ids({model:'silver.orders',unresolved:true}),['pending']);
assert.equal(alignmentUnresolved({status:'unmatched',disposition:'retire_candidate',review_status:'accepted',freshness:'current'}),false);
assert.equal(alignmentUnresolved({status:'unmatched',disposition:'retire_candidate',review_status:'accepted',freshness:'stale'}),true);
assert.equal(el('alignment-table').children.length,3);
el('alignment-changed').checked=true;el('alignment-changed').onchange();assert.match(el('alignment-count').textContent,/2 of 4/);
el('alignment-changed').checked=false;el('alignment-model').value='silver.orders';el('alignment-model').onchange();assert.match(el('alignment-count').textContent,/2 of 4/);
const links=alignmentModelLinks('gold.orders').querySelectorAll('button');assert.equal(links.length,3);
assert.equal(links[1].textContent,'Open code');assert.equal(links[1].getAttribute('title'),files.find(file=>file.id==='1').path);assert.equal(links[1].getAttribute('aria-label'),'Open code: '+files.find(file=>file.id==='1').path);
assert.equal(el('alignment-forward').querySelector('tbody').children[0].children[2].children[0].textContent.split(' · ').filter(label=>label==='Split').length,1);
links[0].onclick();assert.equal(location.hash,'#architecture');listeners.hashchange[0]();assert.equal(inspectedModel,'gold.orders');
assert.equal(el('model').hidden,false);assert.equal(el('architecture').hidden,false);
assert(el('table-inspector').className.includes('drawer-open'));assert.equal(el('table-inspector').getAttribute('role'),'dialog');assert.equal(el('table-inspector').getAttribute('aria-modal'),'true');assert.equal(pendingInspectorModel,null);
closeInspector();links[0].onclick();assert(el('table-inspector').className.includes('drawer-open')); // Same fragment has no new hashchange.
links[1].onclick();assert.equal(location.hash,'#implementation-code');assert.equal(activeFile.id,'1');
links[2].onclick();assert.equal(location.hash,'#changes');assert.equal(el('decisions').scrolled,true);
assert.equal(alignmentModelLinks('outside.model').querySelectorAll('button').length,0);
const extra={...files.find(file=>file.id==='1'),id:'extra-code',path:'models/a_very_long_nested_path/another_model.sql'};files.push(extra);models.find(model=>model.id==='gold.orders').artifact_ids=[extra.id];
const multiple=alignmentModelLinks('gold.orders').querySelectorAll('button');assert.deepEqual(multiple.slice(1,3).map(button=>button.textContent),['Open code 1','Open code 2']);assert.equal(multiple[2].getAttribute('title'),extra.path);assert.equal(multiple[2].getAttribute('aria-label'),'Open code: '+extra.path);files.pop();
assert(el('alignment-print-summary').textContent.includes('unmatched:1'));
let printed=false;globalThis.print=()=>printed=true;el('alignment-print').onclick();assert.equal(printed,true);assert.match(document.body.className,/alignment-print/);listeners.afterprint.forEach(callback=>callback());assert(!document.body.className.includes('alignment-print'));
""", prefix='globalThis.innerWidth=1164;', second_boot=True)

    def test_absent_unrequested_missing_baseline_and_stale(self):
        self.page(self.payload(),"assert.equal(legacyAlignment,null);assert.equal(el('alignment-screen').hidden,true);assert.equal(el('replacement-table').hidden,false);")
        data=self.data()
        for domain in data['legacy_alignment']['domains']: domain['comparison_requested']=False
        self.page(data,"assert.equal(legacyAlignment,null);assert.equal(el('alignment-screen').hidden,true);")
        raw=summary();raw['domains']=raw['domains'][1:]
        data['legacy_alignment']=portal._legacy_alignment_presentation(raw)
        self.page(data,"assert.match(el('alignment-count').textContent,/0 of 0/);assert.match(el('alignment-forward').children[0].textContent,/No baseline comparison/);assert(el('alignment-reverse').children.length);")
        data=self.data();data['legacy_alignment']['rows'][0]['freshness']='stale'
        self.page(data,"assert.equal(alignmentUnresolved(legacyAlignment.rows[0]),true);")

    def test_screen_filters_do_not_reduce_print_downloads_or_portable_package(self):
        data=self.data()
        with tempfile.TemporaryDirectory() as tmp:
            destination=Path(tmp).resolve()/'subset.zip'
            self.page(data,r"""
el('alignment-model').value='silver.orders';renderAlignment();
let saved;download=(name,body)=>saved=body;el('alignment-csv').onclick();assert.equal(saved,legacyAlignment.summary_csv);assert(saved.includes('merge'));
el('alignment-markdown').onclick();assert.equal(saved,legacyAlignment.summary_markdown);assert(saved.includes('unmatched:1'));
let writeExport;download=(name,body)=>{writeExport=body.arrayBuffer().then(buffer=>require('node:fs').writeFileSync(OUTPUT,Buffer.from(buffer)));};
chosen.clear();chosen.add('documentation');updateExport();
el('download-package').onclick().then(()=>writeExport).then(()=>{assert.match(el('messages').textContent,/Candidate subset created/);}).catch(error=>{console.error(error);process.exitCode=1;});
""".replace('OUTPUT',json.dumps(str(destination))))
            self.assertTrue(destination.exists())
            self.assertEqual(portal.verify_delivery(destination)['status'],'integrity_verified')
            with zipfile.ZipFile(destination) as archive:
                rows=list(csv.DictReader(io.StringIO(archive.read('01_Model/legacy-table-alignment.csv').decode())))
                self.assertEqual(len(rows),4)
                self.assertIn('Target model to existing tables',archive.read('01_Model/legacy-table-alignment.md').decode())

    def test_code_only_and_audit_remove_payload_and_generated_comparison(self):
        for audience,categories in [('engineer',['implementation']),('audit',['technical_audit'])]:
            data=self.payload(tuple(categories),audience);data['legacy_alignment']=portal._legacy_alignment_presentation(summary())
            trimmed=copy.deepcopy(data);portal._trim_workflow_details(trimmed)
            self.assertNotIn('legacy_alignment',trimmed)
            self.assertFalse([r for r in portal.generated_deliverables(trimmed) if 'legacy-alignment' in r['id']])
            self.page(data,"""
assert.equal(legacyAlignment,null);const snapshot=JSON.parse(JSON.stringify(data));trimWorkflowDetails(snapshot,new Set(data.selected_categories));assert.equal(snapshot.legacy_alignment,undefined);rebuildGenerated(snapshot).then(rows=>assert(!rows.some(row=>row.id.includes('legacy-alignment'))));
""")

    def test_paginated_long_names_and_safe_text_keep_last_row_in_exports(self):
        raw=summary();raw['domains']=raw['domains'][:1]
        mappings=[]
        for index in range(65):
            row=copy.deepcopy(raw['domains'][0]['mappings'][0]);row.update(id='mapping-'+str(index),rationale='Last explanation '+str(index)+' <script>untrusted()</script>')
            row['legacy_sources'][0]['table_name']='schema.'+'very_long_existing_table_name_'*12
            mappings.append(row)
        raw['domains'][0]['mappings']=mappings
        data=self.data();data['legacy_alignment']=portal._legacy_alignment_presentation(raw)
        self.page(data,r"""
assert.match(el('alignment-count').textContent,/67 of 67/);
assert(el('alignment-forward').querySelectorAll('tr').length<67);
assert(el('alignment-print-summary').textContent.includes('Last explanation 64'));
assert(el('alignment-print-summary').textContent.includes('<script>untrusted()</script>'));
assert.equal(el('alignment-forward').querySelectorAll('script').length,0);
assert(legacyAlignment.summary_csv.includes('Last explanation 64'));
let saved;download=(name,body)=>saved=body;el('alignment-markdown').onclick();assert(saved.includes('Last explanation 64'));
""")


if __name__=='__main__': unittest.main()
