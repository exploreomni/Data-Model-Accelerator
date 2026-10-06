"""File-backed curated semantic handoff and portable omission boundaries."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/data-model-accelerator/scripts'))
import omni_contract as omni
import omni_handoff as handoff
import delivery_portal as portal
from test_omni_contract import files,context
from test_delivery_portal import fixture as portal_fixture


@unittest.skipUnless(omni.yaml is not None and omni.sqlglot is not None,'Pinned YAML/SQL runtime required')
class OmniHandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()
        self.state,self.review=portal_fixture(self.root)
        self.context=context();self.files=files()
        self.state['inputs']['catalogue']['sha256']=self.context['catalogue_sha256']
        self.review['context_sha256']=portal.context_fingerprint(self.state)
        self.result=handoff.build_handoff(self.state,self.files,self.context)
        self.output=self.root/'semantic'
        registration=handoff.write_handoff(self.result,self.output)
        self.review['artifacts']=registration['artifacts'];self.review['omni']=registration['omni']

    def package(self,**kwargs):
        destination=self.root/('test-'+str(len(list(self.root.glob('*.zip'))))+'.zip')
        portal.package_delivery(self.state,self.review,self.output,destination,**kwargs)
        return destination

    def payload(self,path):
        with zipfile.ZipFile(path) as archive:page=archive.read('START_HERE.html').decode()
        return json.loads(page.split('<script id="delivery-data" type="application/json">')[1].split('</script>')[0])

    def test_deterministic_private_candidate_and_exact_native_bytes(self):
        self.assertEqual(self.result,handoff.build_handoff(self.state,self.files,self.context))
        for path,text in self.files.items():self.assertEqual(text,(self.output/'omni/model'/path).read_text())
        self.assertEqual(0o600,(self.output/handoff.CONTEXT_PATH).stat().st_mode&0o777)
        self.assertEqual('pending',self.result['summary']['native_status'])
        self.assertFalse(self.result['summary']['acceptance_ready'])

    def test_reviewer_package_is_curated_without_sql_or_private_context(self):
        path=self.package(audience='reviewer');data=self.payload(path)
        self.assertEqual('selected',data['review']['omni']['evidence_state'])
        self.assertTrue(data['review']['omni']['metrics'])
        with zipfile.ZipFile(path) as archive:
            self.assertFalse(any('MODEL_CONTEXT' in name or name.endswith(('.view','.topic')) for name in archive.namelist()))
            content=archive.read(next(n for n in archive.namelist() if n.endswith('SEMANTIC_REVIEW.json')))
            self.assertNotIn(b'NULLIF',content)
        self.assertEqual('integrity_verified',portal.verify_delivery(path)['status'])

    def test_engineer_files_keep_native_extensions_and_are_verified(self):
        path=self.package(audience='engineer')
        with zipfile.ZipFile(path) as archive:
            self.assertTrue(any(n.endswith('events.view') for n in archive.namelist()))
            self.assertFalse(any('MODEL_CONTEXT' in n for n in archive.namelist()))
        self.assertEqual('integrity_verified',portal.verify_delivery(path)['status'])

    def test_review_distinguishes_topic_selection_from_shared_inventory(self):
        summary=self.result['summary']
        scoped={r['id']:r for r in summary['metrics'] if r['topic']=='activity'}
        self.assertTrue(scoped['events.total']['selected_for_query'])
        self.assertFalse(scoped['events.average']['selected_for_query'])
        self.assertIsNone(next(r for r in summary['metrics'] if r['topic'] is None)['selected_for_query'])
        temporal=next(r for r in summary['dictionary'] if r['topic']=='activity' and r['id']=='events.recorded_at')
        self.assertTrue(temporal['selected_for_query'])
        self.assertIn(b'query_selected,ai_awareness',self.result['artifacts']['omni/SEMANTIC_DICTIONARY.csv']['content'])

    def test_omitted_omni_artifact_removes_the_curated_payload(self):
        path=self.package(audience='engineer',include=['implementation'])
        summary=self.payload(path)['review']['omni']
        self.assertEqual('not_included',summary['evidence_state'])
        self.assertNotIn('metrics',summary);self.assertNotIn('topics',summary)
        self.assertEqual('integrity_verified',portal.verify_delivery(path)['status'])

    def test_status_only_page_does_not_load_unselected_semantic_evidence(self):
        destination=self.root/'STATUS.html';portal.render_engagement(self.state,destination,self.review)
        data=json.loads(destination.read_text().split('<script id="delivery-data" type="application/json">')[1].split('</script>')[0])
        self.assertEqual('not_included',data['review']['omni']['evidence_state'])

    def test_changed_private_context_blocks_curated_only_export(self):
        (self.output/handoff.CONTEXT_PATH).write_text('{}')
        with self.assertRaisesRegex(ValueError,'Omni source artifact changed'):self.package(audience='reviewer')

    def test_changed_native_bytes_blocks_curated_only_export(self):
        (self.output/'omni/model/events.view').write_text('label: Changed\n')
        with self.assertRaisesRegex(ValueError,'Omni source artifact changed'):self.package(audience='reviewer')

    def test_private_context_cannot_be_reclassified_into_reviewer_export(self):
        for record in self.review['artifacts']:
            if record['path']==handoff.CONTEXT_PATH:
                record['category']='documentation';record['audiences']=['reviewer','engineer']
        with self.assertRaisesRegex(ValueError,'audience boundary changed'):self.package(audience='reviewer')

    def test_private_boundary_checked_even_when_semantic_summary_omitted(self):
        for record in self.review['artifacts']:
            if record['path']==handoff.CONTEXT_PATH:
                record['category']='dictionary';record['audiences']=['reviewer','engineer']
        with self.assertRaisesRegex(ValueError,'audience boundary changed'):
            self.package(audience='reviewer',include=['dictionary'])

    def test_native_input_cannot_be_reclassified_as_reviewer_documentation(self):
        for record in self.review['artifacts']:
            if record['path'].endswith('events.view'):
                record['category']='documentation';record['audiences']=['reviewer','engineer']
        with self.assertRaises(ValueError):self.package(audience='reviewer')

    def test_rehashed_forged_review_is_rebuilt_from_inputs(self):
        summary=copy.deepcopy(self.result['summary']);summary['native_status']='passed'
        summary['handoff_sha256']=omni.canonical_hash({k:v for k,v in summary.items() if k!='handoff_sha256'})
        body=handoff._bytes(summary);(self.output/handoff.REVIEW_PATH).write_bytes(body)
        sha=handoff._sha(body);self.review['omni']['sha256']=sha
        for record in self.review['artifacts']:
            if record['id']==self.review['omni']['artifact_id']:record['sha256']=sha
        with self.assertRaisesRegex(ValueError,'handoff.stale_or_changed'):self.package(audience='reviewer')

    def test_context_and_warehouse_changes_are_stale(self):
        for mutation in ('inputs','warehouse'):
            state=copy.deepcopy(self.state)
            if mutation=='inputs':state['inputs']['source']['fingerprint']['value']='d'*64
            else:state['answers']['warehouse']='bigquery'
            with self.assertRaises(ValueError):handoff.verify_handoff(self.result['summary'],state,self.files,self.context)

    def test_svg_has_connected_blocks_for_query_lineage(self):
        self.files['rollup.query.view']='query:\n  base_view: events\n  fields: {events.total: total}\ndimensions:\n  total: {}\n'
        result=handoff.build_handoff(self.state,self.files,self.context)
        svg=result['artifacts']['omni/SEMANTIC_DEPENDENCIES.svg']['content']
        portal._validate_svg(svg)
        self.assertIn(b'<rect',svg);self.assertIn(b'<path',svg)
        self.assertTrue(result['summary']['dependencies'])

    def test_plain_physical_join_has_connected_blocks(self):
        self.files['groups.view']=self.files['events.view'].replace('table_name: EVENTS','table_name: GROUPS')
        self.context['bindings']['groups']=copy.deepcopy(self.context['bindings']['events'])
        self.context['bindings']['groups']['namespace']['table']='GROUPS'
        self.files['relationships']='- {join_from_view: events, join_to_view: groups, join_type: left, relationship_type: many_to_one, on_sql: "${events.id} = ${groups.id}"}\n'
        result=handoff.build_handoff(self.state,self.files,self.context)
        self.assertTrue(any(edge['kind']=='declared_join' for edge in result['summary']['dependencies']))
        self.assertIn(b'<path',result['artifacts']['omni/SEMANTIC_DEPENDENCIES.svg']['content'])

    def test_excluded_topic_fields_remain_explicitly_ineligible(self):
        self.files['activity.topic']='base_view: events\njoins: {}\nfields: [events.id]\nai_fields: [events.total]\n'
        result=handoff.build_handoff(self.state,self.files,self.context)
        row=next(r for r in result['summary']['dictionary'] if r['topic']=='activity' and r['id']=='events.total')
        self.assertFalse(row['selected_for_query']);self.assertTrue(row['selected_for_ai'])
        self.assertEqual('native_qualification_required',row['runtime_eligibility'])

    def test_formula_like_labels_are_safe_csv_and_html_is_escaped(self):
        obj=omni._load(self.files['events.view']);obj['dimensions']['id']['label']='=synthetic_formula'
        obj['dimensions']['id']['description']='<script>synthetic</script>'
        self.files['events.view']=omni.yaml.safe_dump(obj)
        result=handoff.build_handoff(self.state,self.files,self.context)
        self.assertIn(b"'=synthetic_formula",result['artifacts']['omni/SEMANTIC_DICTIONARY.csv']['content'])
        data=portal._presentation(self.state,self.review);data['review']['omni']={'description':'<script>synthetic</script>'}
        self.assertNotIn('<script>synthetic</script>',portal._html(data))

    def test_writer_rejects_existing_directory(self):
        with self.assertRaises(ValueError):handoff.write_handoff(self.result,self.output)

    def test_writer_rejects_unsafe_or_changed_artifact_contract(self):
        for mutation in ('path','content','registration','private_audience'):
            value=copy.deepcopy(self.result)
            if mutation=='path':value['artifacts']['.']={'content':b'x','category':'documentation','audiences':['reviewer']}
            elif mutation=='content':value['artifacts'][handoff.REVIEW_PATH]['content']=b'{}'
            elif mutation=='registration':value['registrations'][0]['sha256']='0'*64
            else:value['artifacts'][handoff.CONTEXT_PATH]['audiences']=['engineer']
            with self.assertRaises(ValueError):handoff.write_handoff(value,self.root/('bad-'+mutation))


class OmniSubsetTests(unittest.TestCase):
    def test_browser_subset_clears_semantic_details(self):
        node=shutil.which('node')
        if not node:self.skipTest('Node runtime unavailable')
        source=(portal.ASSETS/'portal.js').read_text()
        helper=source.split('// BEGIN OMNI SUBSET HELPERS')[1].split('// END OMNI SUBSET HELPERS')[0]
        helper='\n'.join(helper.splitlines()[1:])
        program=helper+"\nconst next={review:{omni:{artifact_id:'id',sha256:'hash',metrics:['PRIVATE_MARKER'],topics:['PRIVATE_MARKER']}}};trimOmniEvidence(next,[]);if(JSON.stringify(next).includes('PRIVATE_MARKER')||next.review.omni.evidence_state!=='not_included')process.exit(1);"
        result=subprocess.run([node,'-e',program],capture_output=True,text=True)
        self.assertEqual(0,result.returncode,result.stderr)


if __name__=='__main__':unittest.main()
