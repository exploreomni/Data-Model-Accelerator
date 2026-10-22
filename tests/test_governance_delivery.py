"""One scoped canonical snapshot reaches the portal and complete portable exports."""
import base64
import copy
import csv
import io
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/data-model-accelerator/scripts'))
import delivery_portal as portal
import governance_delivery as delivery
import migration_inventory as inventory
import naming_governance as naming
import consumer_contracts as consumers
import test_engagement_stages as fixtures
import test_migration_plan_exports as export_fixtures
from ae_common import hash_json


class GovernanceDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.h=fixtures.StageTests('test_host_attributed_review_opens_candidates_not_deployment')
        self.h.setUp(); self.addCleanup(self.h.doCleanups)
        self.state=self.h.state
        self.state['workflow']['design']['entities'][2]['domain']='catalog'
        naming.configure(self.state,dict(schema_version=1,policy=dict(schema_version=1,profile='preserve'),
            decision_reference='synthetic://decision'))
        naming.register(self.state,{'schema_version':1,'resources':[
            dict(id='identity.'+e['id'],entity_id=e['id'],source_id='legacy:'+e['id'],original_name=e['name'],
                 target_name=e['name'],physical_alias=None,source_relation=None,existing=False,layer=e['layer'],
                 role='fact',business_stem=e['name'],domain=e['domain'],namespace=['dev','models'],evidence_refs=['synthetic://source'])
            for e in self.state['workflow']['design']['entities']]})
        rows=[dict(id='requested-'+str(i),source_namespace='legacy',native_id='table_'+str(i),
                   domain_ids=['commerce'],evidence_refs=[]) for i in range(505)]
        rows.append(dict(id='private',source_namespace='other',native_id='private_catalog',domain_ids=['catalog'],evidence_refs=[]))
        inventory.register(self.state,dict(schema_version=1,registers=[dict(id='tickets',kind='ticket',evidence_refs=[],rows=rows)]),self.h.run)
        consumers.register(self.state,dict(schema_version=1,contracts=[dict(id='orders-public',source_id='legacy:orders',
            entity_id='orders',consumer_ids=['report-orders'],baseline=dict(materialization='table',columns=[
                dict(name='removed_public_field',type='string',description='Source public field')]),
            proposed_materialization='view',evidence_refs=['synthetic://baseline'])]))

    def test_complete_scoped_csv_and_matching_word_excel_snapshots(self):
        data=delivery.project(self.state,['orders','customers'])
        self.assertNotIn('private_catalog',json.dumps(data))
        self.assertEqual(data['snapshot_sha256'],hash_json({k:v for k,v in data.items() if k!='snapshot_sha256'}))
        exported={Path(r['path']).name:r['content'] for r in delivery.files(data)}
        rows=list(csv.reader(io.StringIO(exported['requested-scope.csv'].decode())))
        self.assertEqual(len(rows)-1,505)
        self.assertTrue(all(r[4]=='missing_evidence' for r in rows[1:]))
        raw=export_fixtures.fixture(); raw['domains'][0]['governed_review']=data
        files=export_fixtures.files(raw)
        workbook=export_fixtures.workbook(files['inventory.xlsx']['content'])
        self.assertEqual(len(workbook['Requested scope'][0])-1,505)
        self.assertEqual(len(workbook['Governed names'][0])-1,2)
        _,parts=export_fixtures.document(files['migration-plan.docx']['content']);text='\n'.join(parts)
        self.assertIn(data['snapshot_sha256'],text)
        self.assertIn('removed_public_field',text); self.assertIn('table_504',text)

    def test_portal_exports_share_snapshot_and_code_only_removes_details(self):
        data=portal._presentation(self.state,None)
        self.assertEqual(sum(d['counts']['requested'] for d in data['workflow']['governance']['inventory']['domains']),506)
        # Explicit review subsets are projected before disclosure; use canonical subset helper here.
        data['workflow']['governance']=delivery.project(self.state,['orders','customers'])
        rendered=portal._html(data)
        self.assertIn('id="governed-review"',rendered)
        data.update(selected_categories=['dictionary','documentation'],package_layout_version=2)
        records=portal.generated_deliverables(data)
        selected=[r for r in records if r['id'].startswith('generated:governance:')]
        self.assertTrue(selected)
        self.assertTrue(all(r['path'].startswith('05_Mappings/') for r in selected))
        self.assertFalse(any(b'private_catalog' in base64.b64decode(r['base64']) for r in selected))
        data['selected_categories']=['documentation']
        self.assertFalse(any(r['id'].startswith('generated:governance:') for r in portal.generated_deliverables(data)))
        portal._trim_workflow_details(data)
        self.assertNotIn('governance',data['workflow'])

    def test_csv_formula_payload_and_older_engagement_behavior(self):
        raw=delivery.project(self.state,['orders'])
        raw['identities'][0]['source_id']='=HYPERLINK("untrusted")'
        contents=next(r['content'] for r in delivery.files(raw) if r['path'].endswith('governed-names.csv'))
        cells=list(csv.reader(io.StringIO(contents.decode())))
        self.assertTrue(cells[1][2].startswith("'="))
        for key in ('naming_governance','migration_inventory','consumer_contracts'):
            self.state['workflow'].pop(key,None)
        self.assertIsNone(delivery.project(self.state))


if __name__=='__main__': unittest.main()
